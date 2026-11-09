from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from urllib.parse import quote

from . import webparse as wp
from .auth import AuthState
from .browser import BrowserHost, snapshot
from .constants import CONTENT_URL, HOME
from .errors import ActionFailed, BadInput, NotFound, NotSupported, PageChanged, TikSocketError, Unavailable
from .models import ActionResult, Comment, Hashtag, Notice, Page, Post, User
from .web import UNIVERSAL_JS, WebSession

log = logging.getLogger("tiksocket")

FOLLOW = ("[data-e2e=follow-button]", "[data-e2e=feed-follow]", "button[data-e2e*=follow]")
USER_MORE = ("[data-e2e=user-more]", "button[aria-label=Actions]")
MESSAGE = ("[data-e2e=message-button]",)
LIKE = ("[data-e2e=like-icon]", "[data-e2e=browse-like-icon]", "button[aria-label^='Like video']")
FAVORITE = ("[data-e2e=favorite-icon]", "[data-e2e=undefined-favorite-icon]", "button[aria-label*='Favorites']")
COMMENTS = ("[data-e2e=comment-icon]", "[data-e2e=browse-comment-icon]", "button[aria-label^='Read or add comments']")
SHARE = ("[data-e2e=share-icon]", "button[aria-label^='Share video']")
COMMENT_INPUT = ("[data-e2e=comment-input] [contenteditable=true]", "[data-e2e=comment-text] [contenteditable=true]",
                 "[data-e2e=comment-input] div[role=textbox]", "div[contenteditable=true][role=textbox]")
COMMENT_POST = ("[data-e2e=comment-post]", "div[data-e2e=comment-post]", "button:has-text('Post')")
COMMENT_ITEM = ("[data-e2e=comment-level-1]", "[data-e2e=comment-level-2]")
COMMENT_LIKE = ("[data-e2e=comment-like-icon]", "[aria-label*='Like comment' i]")
COMMENT_REPLY = ("[data-e2e=comment-reply-1]", "[data-e2e=comment-reply-2]", "span:has-text('Reply')")
COMMENT_MORE = ("[data-e2e=comment-more-icon]", "[aria-label*='more' i]")
MENU = ("[role=menu] [role=menuitem]", "[data-floating-ui-portal] [role=button]", "[data-floating-ui-portal] li",
        "[data-floating-ui-portal] button", "[data-floating-ui-portal] div[tabindex]", "[role=dialog] button")
DIALOG_BUTTON = ("[role=dialog] button", ".TUXModal button", "[data-floating-ui-portal] button")
EDIT = ("[data-e2e=edit-profile-entrance]", "button:has-text('Edit profile')")
EDIT_NAME = ("[data-e2e=edit-profile-name-input] input", "[data-e2e=edit-profile-popup] input[placeholder=Name]",
             "[data-e2e=edit-profile-name] input")
EDIT_USERNAME = ("[data-e2e=edit-profile-username-input] input", "[data-e2e=edit-profile-popup] input[placeholder=Username]",
                 "[data-e2e=edit-profile-username] input")
EDIT_BIO = ("[data-e2e=edit-profile-bio-input]", "[data-e2e=edit-profile-popup] textarea")
EDIT_SAVE = ("[data-e2e=edit-profile-save]",)
EDIT_PHOTO = ("[data-e2e=edit-profile-popup] input[type=file]", "[data-e2e=edit-profile-photo] input[type=file]")
FOLLOWERS_COUNT = ("[data-e2e=followers-count]", "[data-e2e=followers]")
FOLLOW_PATHS = ("/api/commit/follow/user", "/commit/follow")
BLOCK_PATHS = ("/api/user/block", "/block/")
LIKE_PATHS = ("/api/commit/item/digg", "/item/digg")
FAVORITE_PATHS = ("/api/item/collect", "/collect/")
COMMENT_PATHS = ("/api/comment/publish",)
COMMENT_LIKE_PATHS = ("/api/comment/digg",)
COMMENT_DELETE_PATHS = ("/api/comment/delete",)
REPOST_PATHS = ("/tiktok/v1/upvote", "/upvote/", "/api/repost")
PROFILE_PATHS = ("/api/update/profile", "/user/profile/update", "/passport/web/user/update", "/update/profile",
                 "/api/user/update")
STUDIO_LIST = ("/tiktok/creator/manage/item_list",)
DELETE_POST_PATHS = ("/api/aweme/delete", "/aweme/delete", "/item/delete", "/api/post/delete", "/tiktokstudio/api")
PRIVACY_PATHS = ("/aweme/modify", "/item/modify", "/api/post/edit", "/visibility", "/tiktokstudio/api", "/privacy")
PIN_PATHS = ("/pin", "/stick")
FOLLOWERS_SCENE, FOLLOWING_SCENE = 67, 21
NOTICE_ALL = 500


def _word(*words: str) -> re.Pattern:
    return re.compile(r"^\s*(" + "|".join(re.escape(w) for w in words) + r")\s*$", re.I)


class Actions:
    def __init__(self, host: BrowserHost, auth: AuthState):
        self.web = WebSession(host, auth)
        self.auth = auth

    @property
    def me(self) -> str:
        return str(self.auth.load_profile().get("username") or "").lower()

    async def _guard(self, coro):
        try:
            return await coro
        except TikSocketError:
            await snapshot(self.web.view, self.auth.debug_folder(), "web-error.png")
            raise
        finally:
            await self.web.save()

    def _name(self, raw: str) -> str:
        name = wp.username(raw)
        if not name:
            raise BadInput("give a TikTok username like @name or a profile link")
        return name

    def _post(self, raw: str) -> tuple[str, str, str]:
        user, kind, pid = wp.post_ref(raw)
        if not pid:
            raise BadInput("give a post link like https://www.tiktok.com/@user/video/123 or a post id")
        return user, kind, pid

    async def user(self, raw: str) -> User:
        name = self._name(raw)
        async with self.web.lock:
            data = await self._guard(self.web.universal(f"{HOME}@{name}", "webapp.user-detail"))
        found = wp.user_from_detail(data.get("webapp.user-detail") or {})
        if found is None:
            raise NotFound(f"user @{name} not found")
        return found

    async def search_users(self, query: str, cursor: str = "0") -> Page:
        if not (query or "").strip():
            raise BadInput("empty search")
        async with self.web.lock:
            data = await self._guard(self.web.api("/api/search/user/full/", {"keyword": query.strip(), "cursor": cursor}))
        rows, page = wp.users_from_search(data)
        return Page(items=rows, cursor=page["cursor"], has_more=page["has_more"])

    async def _people(self, raw: str, scene: int, cursor: str, count: int) -> Page:
        target = await self.user(raw)
        params = {"secUid": target.sec_uid, "count": max(1, min(count, 50)), "maxCursor": 0, "minCursor": cursor or 0,
                  "scene": scene}
        async with self.web.lock:
            data = await self._guard(self.web.api("/api/user/list/", params))
        rows, page = wp.users_from_list(data)
        return Page(items=rows, cursor=page["min_cursor"], has_more=page["has_more"], total=page["total"])

    async def followers(self, raw: str = "", cursor: str = "0", count: int = 30) -> Page:
        return await self._people(raw or self.me, FOLLOWERS_SCENE, cursor, count)

    async def following(self, raw: str = "", cursor: str = "0", count: int = 30) -> Page:
        return await self._people(raw or self.me, FOLLOWING_SCENE, cursor, count)

    async def relationship(self, raw: str) -> dict:
        found = await self.user(raw)
        return {"username": found.username, "relation": found.relation, "following": found.is_following,
                "friends": found.is_friend, "private": found.private}

    async def _follow(self, raw: str, want: bool) -> ActionResult:
        name = self._name(raw)
        if name == self.me:
            raise BadInput("you cannot follow yourself")
        current = await self.user(name)
        if current.is_following == want:
            return ActionResult(action="follow" if want else "unfollow", target=name, changed=False)

        async def act():
            await self.web.goto(f"{HOME}@{name}")
            await self.web.press(FOLLOW)
            if not want:
                confirm = await self.web.find(DIALOG_BUTTON, 2.5, _word("Unfollow"))
                if confirm is not None:
                    await confirm.click(timeout=4000)

        async with self.web.lock:
            data = await self._guard(self.web.expect(FOLLOW_PATHS, act))
        return ActionResult(action="follow" if want else "unfollow", target=name,
                            detail={"follow_status": data.get("follow_status", data.get("followStatus"))})

    async def follow(self, raw: str) -> ActionResult:
        return await self._follow(raw, True)

    async def unfollow(self, raw: str) -> ActionResult:
        return await self._follow(raw, False)

    async def _block(self, raw: str, want: bool) -> ActionResult:
        name = self._name(raw)

        async def act():
            await self.web.goto(f"{HOME}@{name}")
            if want:
                await self.web.press(USER_MORE)
                await self.web.press(MENU, 5, _word("Block"))
                confirm = await self.web.find(DIALOG_BUTTON, 5, _word("Block", "Confirm"))
                if confirm is None:
                    raise PageChanged("block confirmation not found")
                await confirm.click(timeout=4000)
            else:
                button = await self.web.find(("button", "[role=button]"), 4, _word("Unblock"))
                if button is None:
                    await self.web.press(USER_MORE)
                    await self.web.press(MENU, 5, _word("Unblock"))
                else:
                    await button.click(timeout=4000)
                confirm = await self.web.find(DIALOG_BUTTON, 3, _word("Unblock", "Confirm"))
                if confirm is not None:
                    await confirm.click(timeout=4000)

        async with self.web.lock:
            await self._guard(self.web.expect(BLOCK_PATHS, act))
        return ActionResult(action="block" if want else "unblock", target=name)

    async def block(self, raw: str) -> ActionResult:
        return await self._block(raw, True)

    async def unblock(self, raw: str) -> ActionResult:
        return await self._block(raw, False)

    async def remove_follower(self, raw: str) -> ActionResult:
        name = self._name(raw)

        async def act():
            await self.web.goto(f"{HOME}@{self.me}")
            await self.web.press(FOLLOWERS_COUNT)
            row = await self.web.find(("[role=dialog] li", "[role=dialog] [data-e2e*=user]", "[role=dialog] div"), 10,
                                      re.compile(re.escape(name), re.I))
            if row is None:
                raise NotFound(f"@{name} is not in your followers list")
            button = row.locator("button").filter(has_text=_word("Remove", "Remove follower")).first
            if not await button.count():
                more = row.locator("button[aria-label], [role=button][aria-label]").first
                await more.click(timeout=4000)
                await self.web.press(MENU, 4, _word("Remove", "Remove follower", "Remove this follower"))
            else:
                await button.click(timeout=4000)
            confirm = await self.web.find(DIALOG_BUTTON, 4, _word("Remove"))
            if confirm is not None:
                await confirm.click(timeout=4000)

        async with self.web.lock:
            await self._guard(self.web.expect(("/remove/follower", "/follower/remove", "/commit/follow", "/remove"), act))
        return ActionResult(action="remove_follower", target=name)

    async def post(self, raw: str) -> Post:
        user, kind, pid = self._post(raw)
        url = wp.post_url(user, kind, pid)
        scope: dict = {}

        async def act():
            page = await self.web.goto(url, settle=2000)
            for _ in range(6):
                scope.update(await page.evaluate(UNIVERSAL_JS) or {})
                if scope.get("webapp.video-detail"):
                    return
                await page.wait_for_timeout(800)

        async with self.web.lock:
            replies = await self._guard(self.web.collect("/api/item/detail/", act, wait=6,
                                                         until=lambda rows: any(r.get("itemInfo") for r in rows)))
        for data in [scope.get("webapp.video-detail") or {}, *replies]:
            found = wp.post_from_detail(data)
            if found is not None and found.id == pid:
                return found
        raise NotFound(f"post {pid} not found")

    async def own_posts(self, limit: int = 50) -> list[Post]:
        posts: dict[str, Post] = {}

        async def act():
            await self.web.goto(CONTENT_URL, settle=1500)

        async with self.web.lock:
            pages = await self._guard(self.web.collect(STUDIO_LIST, act, wait=20,
                                                       until=lambda rows: any(r.get("item_list") for r in rows)))
            page = self.web.view

            async def scroll():
                await page.mouse.wheel(0, 8000)

            for _ in range(10):
                for data in pages:
                    for row in wp.posts_from_manage(data, self.me)[0]:
                        posts.setdefault(row.id, row)
                if len(posts) >= limit or not pages or not pages[-1].get("has_more"):
                    break
                pages = await self.web.collect(STUDIO_LIST, scroll, wait=8)
                if not pages:
                    break
        return list(posts.values())[:limit]

    async def user_posts(self, raw: str = "", limit: int = 30) -> list[Post]:
        name = self._name(raw or self.me)
        if name == self.me:
            return await self.own_posts(limit)
        posts: dict[str, Post] = {}

        async def act():
            await self.web.goto(f"{HOME}@{name}", settle=1500)

        async with self.web.lock:
            pages = await self._guard(self.web.collect("/api/post/item_list/", act, wait=15,
                                                       until=lambda rows: sum(len(r.get("itemList") or []) for r in rows) > 0))
            for data in pages:
                for row in wp.posts_from_list(data)[0]:
                    posts.setdefault(row.id, row)
            page = self.web.view

            async def scroll():
                await page.mouse.wheel(0, 6000)

            for _ in range(20):
                if len(posts) >= limit or not pages or not pages[-1].get("hasMore"):
                    break
                pages = await self.web.collect("/api/post/item_list/", scroll, wait=8)
                if not pages:
                    break
                for data in pages:
                    for row in wp.posts_from_list(data)[0]:
                        posts.setdefault(row.id, row)
            await self.web.save()
        return list(posts.values())[:limit]

    async def comments(self, raw: str, limit: int = 50) -> list[Comment]:
        user, kind, pid = self._post(raw)
        rows: dict[str, Comment] = {}

        async def act():
            await self.web.goto(wp.post_url(user, kind, pid), settle=2500)
            await self.web.press(COMMENTS)

        async with self.web.lock:
            pages = await self._guard(self.web.collect("/api/comment/list/", act, wait=12))
            for data in pages:
                for row in wp.comments_from_list(data, pid)[0]:
                    rows.setdefault(row.id, row)
            page = self.web.view

            async def scroll():
                box = page.locator(", ".join(COMMENT_ITEM)).last
                if await box.count():
                    await box.scroll_into_view_if_needed(timeout=3000)
                await page.mouse.wheel(0, 3000)

            for _ in range(10):
                if len(rows) >= limit or not pages or not pages[-1].get("has_more"):
                    break
                pages = await self.web.collect("/api/comment/list/", scroll, wait=6)
                for data in pages:
                    for row in wp.comments_from_list(data, pid)[0]:
                        rows.setdefault(row.id, row)
            await self.web.save()
        return list(rows.values())[:limit]

    async def _toggle(self, raw: str, selectors: tuple, paths: tuple, field: str, want: bool, name: str) -> ActionResult:
        current = await self.post(raw)
        if bool(getattr(current, field)) == want:
            return ActionResult(action=name, target=current.id, changed=False)

        async def act():
            await self.web.goto(current.url)
            await self.web.press(selectors)

        async with self.web.lock:
            await self._guard(self.web.expect(paths, act))
        return ActionResult(action=name, target=current.id)

    async def like(self, raw: str) -> ActionResult:
        return await self._toggle(raw, LIKE, LIKE_PATHS, "liked", True, "like")

    async def unlike(self, raw: str) -> ActionResult:
        return await self._toggle(raw, LIKE, LIKE_PATHS, "liked", False, "unlike")

    async def favorite(self, raw: str) -> ActionResult:
        return await self._toggle(raw, FAVORITE, FAVORITE_PATHS, "saved", True, "favorite")

    async def unfavorite(self, raw: str) -> ActionResult:
        return await self._toggle(raw, FAVORITE, FAVORITE_PATHS, "saved", False, "unfavorite")

    async def _repost(self, raw: str, want: bool) -> ActionResult:
        user, kind, pid = self._post(raw)
        if user and user.lower() == self.me:
            raise BadInput("you cannot repost your own post")
        label = _word("Repost") if want else _word("Remove repost", "Undo repost", "Reposted")

        async def act():
            await self.web.goto(wp.post_url(user, kind, pid))
            await self.web.press(SHARE)
            await self.web.press(MENU + ("[data-e2e*=repost]",), 5, label)
            confirm = await self.web.find(DIALOG_BUTTON, 2, _word("Remove", "Repost", "Confirm"))
            if confirm is not None:
                await confirm.click(timeout=3000)

        async with self.web.lock:
            await self._guard(self.web.expect(REPOST_PATHS, act))
        return ActionResult(action="repost" if want else "undo_repost", target=pid)

    async def repost(self, raw: str) -> ActionResult:
        return await self._repost(raw, True)

    async def undo_repost(self, raw: str) -> ActionResult:
        return await self._repost(raw, False)

    async def _write_comment(self, text: str) -> None:
        page = self.web.view
        box = await self.web.find(COMMENT_INPUT, 10)
        if box is None:
            raise PageChanged("comment box not found")
        await box.click(timeout=4000)
        await page.keyboard.insert_text(text)
        await page.wait_for_timeout(500)
        button = await self.web.find(COMMENT_POST, 3)
        if button is not None:
            await button.click(timeout=4000)
        else:
            await page.keyboard.press("Enter")

    async def comment(self, raw: str, text: str) -> Comment:
        user, kind, pid = self._post(raw)
        text = (text or "").strip()
        if not text or len(text) > 150:
            raise BadInput("comments are 1 to 150 characters")

        async def act():
            await self.web.goto(wp.post_url(user, kind, pid), settle=2500)
            await self.web.press(COMMENTS)
            await self._write_comment(text)

        async with self.web.lock:
            data = await self._guard(self.web.expect(COMMENT_PATHS, act))
        return wp.comment_from_publish(data) or Comment(post_id=pid, text=text, author=self.me)

    async def _open_comment(self, raw: str, comment_id: str):
        known = {row.id: row for row in await self.comments(raw, limit=200)}
        target = known.get(str(comment_id))
        if target is None:
            raise NotFound(f"comment {comment_id} not found on this post")
        item = await self.web.find(COMMENT_ITEM, 8, re.compile(re.escape(target.text[:60])))
        if item is None:
            raise NotFound("comment is not visible on the page")
        holder = item.locator("xpath=ancestor::*[.//*[@data-e2e='comment-like-icon' or contains(@data-e2e,'comment-reply')]][1]")
        await item.hover(timeout=3000)
        return target, holder if await holder.count() else item

    async def reply_comment(self, raw: str, comment_id: str, text: str) -> Comment:
        text = (text or "").strip()
        if not text or len(text) > 150:
            raise BadInput("replies are 1 to 150 characters")

        async def act():
            _, holder = await self._open_comment(raw, comment_id)
            reply = holder.locator(", ".join(COMMENT_REPLY)).first
            if not await reply.count():
                raise PageChanged("reply button not found")
            await reply.click(timeout=4000)
            await self._write_comment(text)

        data = await self._guard(self.web.expect(COMMENT_PATHS, act))
        found = wp.comment_from_publish(data)
        return found or Comment(text=text, author=self.me, reply_to=str(comment_id))

    async def like_comment(self, raw: str, comment_id: str) -> ActionResult:
        async def act():
            target, holder = await self._open_comment(raw, comment_id)
            if target.liked:
                raise _Done()
            icon = holder.locator(", ".join(COMMENT_LIKE)).first
            if not await icon.count():
                raise PageChanged("comment like button not found")
            await icon.click(timeout=4000)

        try:
            await self._guard(self.web.expect(COMMENT_LIKE_PATHS, act))
        except _Done:
            return ActionResult(action="like_comment", target=str(comment_id), changed=False)
        return ActionResult(action="like_comment", target=str(comment_id))

    async def delete_comment(self, raw: str, comment_id: str) -> ActionResult:
        async def act():
            target, holder = await self._open_comment(raw, comment_id)
            if target.author.lower() != self.me:
                raise BadInput("you can only delete your own comments")
            more = holder.locator(", ".join(COMMENT_MORE)).first
            if not await more.count():
                raise PageChanged("comment menu not found")
            await more.click(timeout=4000)
            await self.web.press(MENU, 4, _word("Delete"))
            confirm = await self.web.find(DIALOG_BUTTON, 4, _word("Delete"))
            if confirm is not None:
                await confirm.click(timeout=4000)

        await self._guard(self.web.expect(COMMENT_DELETE_PATHS, act))
        return ActionResult(action="delete_comment", target=str(comment_id))

    async def _studio_row(self, pid: str):
        await self.web.goto(CONTENT_URL, settle=5000)
        row = await self.web.find((f"[data-tt*='{pid}']", f"a[href*='{pid}']"), 12)
        if row is None:
            raise NotFound(f"post {pid} is not in your TikTok Studio posts")
        holder = row.locator("xpath=ancestor::*[.//button][1]")
        return holder if await holder.count() else row

    async def _studio_menu(self, pid: str, label: re.Pattern, paths: tuple, confirm: re.Pattern | None) -> None:
        async def act():
            holder = await self._studio_row(pid)
            await holder.hover(timeout=3000)
            buttons = holder.locator("button[aria-label], [role=button][aria-label], button:has(svg)")
            if not await buttons.count():
                raise PageChanged("post menu not found")
            await buttons.last.click(timeout=4000)
            await self.web.press(MENU, 5, label)
            if confirm is not None:
                button = await self.web.find(DIALOG_BUTTON, 5, confirm)
                if button is not None:
                    await button.click(timeout=4000)

        await self._guard(self.web.expect(paths, act))

    async def delete_post(self, raw: str) -> ActionResult:
        _, _, pid = self._post(raw)
        async with self.web.lock:
            await self._studio_menu(pid, _word("Delete"), DELETE_POST_PATHS, _word("Delete"))
        return ActionResult(action="delete_post", target=pid)

    async def pin_post(self, raw: str, pin: bool = True) -> ActionResult:
        _, _, pid = self._post(raw)
        label = _word("Pin", "Pin to top") if pin else _word("Unpin")
        async with self.web.lock:
            try:
                await self._studio_menu(pid, label, PIN_PATHS + DELETE_POST_PATHS[-1:], None)
            except PageChanged as exc:
                raise NotSupported("TikTok web did not offer pinning for this post, use the app") from exc
        return ActionResult(action="pin" if pin else "unpin", target=pid)

    async def post_settings(self, raw: str, who_can_view: str = "", comments: bool | None = None) -> ActionResult:
        _, _, pid = self._post(raw)
        labels = {"everyone": _word("Everyone", "Public"), "friends": _word("Friends"),
                  "only_me": _word("Only you", "Only me", "Private")}
        if who_can_view and who_can_view not in labels:
            raise BadInput("who_can_view is everyone, friends or only_me")
        if not who_can_view and comments is None:
            raise BadInput("nothing to change")

        async def act():
            holder = await self._studio_row(pid)
            await holder.hover(timeout=3000)
            edit = holder.locator("button[aria-label*=edit i], a[href*=edit], button:has-text('Edit')").first
            if not await edit.count():
                raise NotSupported("TikTok web did not offer post settings here, use the app")
            await edit.click(timeout=4000)
            await self.web.page()
            if who_can_view:
                await self.web.press(("[role=combobox]", "button:has-text('Everyone')", "button:has-text('Friends')",
                                      "button:has-text('Only you')"), 8)
                await self.web.press(("[role=option]", "[role=menuitem]", "li"), 4, labels[who_can_view])
            if comments is not None:
                box = await self.web.find(("label:has-text('comment') input[type=checkbox]",
                                           "label:has-text('Comment') [role=checkbox]", "[role=switch]"), 5)
                if box is not None:
                    state = await box.get_attribute("aria-checked")
                    checked = state == "true" if state is not None else await box.is_checked()
                    if checked != comments:
                        await box.click(timeout=3000, force=True)
            await self.web.press(("button:has-text('Save')", "button:has-text('Post')", "button:has-text('Update')"), 6)

        async with self.web.lock:
            await self._guard(self.web.expect(PRIVACY_PATHS, act, wait=30))
        return ActionResult(action="post_settings", target=pid,
                            detail={"who_can_view": who_can_view, "comments": comments})

    async def search_posts(self, query: str, cursor: str = "0") -> Page:
        query = (query or "").strip()
        if not query:
            raise BadInput("empty search")
        async with self.web.lock:
            try:
                data = await self._guard(self.web.api("/api/search/general/full/", {"keyword": query, "offset": cursor}))
            except Unavailable:
                data = {}
            rows, page = wp.posts_from_search(data)
            if not rows and cursor in ("", "0"):
                async def act():
                    await self.web.goto(f"{HOME}search?q={quote(query)}", settle=1500)

                for found in await self.web.collect(("/api/search/general/full/", "/api/search/item/full/"), act, wait=15):
                    more, page = wp.posts_from_search(found)
                    rows += more or wp.posts_from_list(found)[0]
        return Page(items=rows, cursor=page["cursor"], has_more=page["has_more"])

    async def hashtag(self, name: str) -> Hashtag:
        tag = (name or "").strip().lstrip("#")
        if not tag:
            raise BadInput("empty hashtag")
        async with self.web.lock:
            data = await self._guard(self.web.api("/api/challenge/detail/", {"challengeName": tag}))
        found = wp.hashtag_from_detail(data)
        if found is None:
            raise NotFound(f"#{tag} not found")
        return found

    async def hashtag_posts(self, name: str, limit: int = 30) -> list[Post]:
        tag = (name or "").strip().lstrip("#")
        if not tag:
            raise BadInput("empty hashtag")

        async def act():
            await self.web.goto(f"{HOME}tag/{tag}", settle=1500)

        async with self.web.lock:
            pages = await self._guard(self.web.collect("/api/challenge/item_list/", act, wait=12))
        rows: dict[str, Post] = {}
        for data in pages:
            for row in wp.posts_from_list(data)[0]:
                rows.setdefault(row.id, row)
        if not rows:
            for row in (await self.search_posts(f"#{tag}")).items:
                rows.setdefault(row.id, row)
        return list(rows.values())[:limit]

    async def feed(self, kind: str = "foryou", count: int = 10) -> list[Post]:
        path = {"foryou": "/api/recommend/item_list/", "explore": "/api/explore/item_list/"}.get(kind)
        if path is None:
            raise BadInput("feed is foryou or explore")
        params = {"count": max(1, min(count, 30))}
        if kind == "explore":
            params["categoryType"] = 120
        async with self.web.lock:
            data = await self._guard(self.web.api(path, params))
        return wp.posts_from_list(data)[0][:count]

    async def notifications(self, count: int = 30, kind: str = "") -> list[Notice]:
        group = [{"count": max(1, min(count, 50)), "is_mark_read": 0, "group": NOTICE_ALL, "max_time": 0, "min_time": 0}]
        async with self.web.lock:
            data = await self._guard(self.web.api("/api/notice/multi/", {"group_list": json.dumps(group)}))
        rows = wp.notices_from(data)[0]
        return [row for row in rows if not kind or row.kind == kind]

    async def download(self, raw: str, target: str | Path | None = None) -> bytes | Path:
        found = await self.post(raw)
        url = found.download_url or found.play_url
        if not url:
            raise NotSupported("this post has no downloadable video, photo posts expose image links in post.images")
        async with self.web.lock:
            await self.web.page()
            response = await self.web.context.request.get(url, headers={"Referer": HOME}, timeout=120000)
        if not response.ok:
            raise ActionFailed(f"download failed with {response.status}")
        blob = await response.body()
        if target is None:
            return blob
        path = Path(target)
        path.write_bytes(blob)
        return path

    async def update_profile(self, nickname: str | None = None, username: str | None = None, bio: str | None = None,
                             avatar: str | Path | bytes | None = None) -> User:
        if nickname is None and username is None and bio is None and avatar is None:
            raise BadInput("nothing to change")
        if username is not None and not wp.USERNAME.match(username or ""):
            raise BadInput("usernames use letters, digits, underscore and dot, up to 30 characters")
        if bio is not None and len(bio) > 80:
            raise BadInput("bio is at most 80 characters")
        if nickname is not None and not (0 < len(nickname) <= 30):
            raise BadInput("name is 1 to 30 characters")
        temp = None
        if isinstance(avatar, (bytes, bytearray)):
            import tempfile

            handle = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
            handle.write(avatar)
            handle.close()
            temp = handle.name
            avatar = temp
        page = None

        async def fill(selectors, value):
            box = await self.web.find(selectors, 6)
            if box is None:
                raise PageChanged("profile field not found")
            await box.click(timeout=3000)
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Delete")
            if value:
                await page.keyboard.insert_text(value)
            await page.wait_for_timeout(400)

        async def act():
            nonlocal page
            page = await self.web.goto(f"{HOME}@{self.me}")
            await self.web.press(EDIT)
            if avatar is not None:
                upload = await self.web.find(EDIT_PHOTO, 6)
                if upload is None:
                    upload = page.locator("[data-e2e=edit-profile-popup] input[type=file]").first
                await upload.set_input_files(str(avatar))
                apply = await self.web.find(DIALOG_BUTTON, 10, _word("Apply", "Save", "Confirm"))
                if apply is not None:
                    await apply.click(timeout=4000)
                    await page.wait_for_timeout(1500)
            if username is not None:
                await fill(EDIT_USERNAME, username)
            if nickname is not None:
                await fill(EDIT_NAME, nickname)
            if bio is not None:
                await fill(EDIT_BIO, bio)
            await self.web.press(EDIT_SAVE)
            confirm = await self.web.find(DIALOG_BUTTON, 3, _word("Confirm", "Set username", "Save"))
            if confirm is not None:
                await confirm.click(timeout=4000)

        try:
            async with self.web.lock:
                await self._guard(self.web.expect(PROFILE_PATHS + ("/upload",), act, wait=30))
        finally:
            if temp:
                Path(temp).unlink(missing_ok=True)
        new = username.lower() if username else self.me
        profile = self.auth.load_profile()
        if username:
            profile["username"] = new
        if nickname:
            profile["nickname"] = nickname
        self.auth.save_profile(profile)
        return await self.user(new)

    async def set_private(self, private: bool) -> ActionResult:
        async with self.web.lock:
            page = await self.web.goto(f"{HOME}setting", settle=5000)
            row = await self.web.find(("div", "section", "li"), 10, re.compile(r"^\s*Private account", re.I))
            if row is None:
                raise NotSupported("TikTok web did not show the private account setting, use the app")
            switch = row.locator("xpath=ancestor-or-self::*[.//*[@role='switch' or @type='checkbox']][1]")
            switch = switch.locator("[role=switch], input[type=checkbox]").first
            if not await switch.count():
                raise PageChanged("private account switch not found")
            state = await switch.get_attribute("aria-checked")
            current = state == "true" if state is not None else await switch.is_checked()
            if current == private:
                return ActionResult(action="set_private", target=self.me, changed=False, detail={"private": private})
            await switch.click(timeout=4000, force=True)
            confirm = await self.web.find(DIALOG_BUTTON, 4, _word("Switch", "Confirm", "Switch to private",
                                                                   "Switch to public", "Turn on", "Turn off"))
            if confirm is not None:
                await confirm.click(timeout=4000)
            await page.wait_for_timeout(2500)
            state = await switch.get_attribute("aria-checked")
            now = state == "true" if state is not None else await switch.is_checked()
            await self.web.save()
        if now != private:
            raise ActionFailed("TikTok kept the old privacy setting")
        return ActionResult(action="set_private", target=self.me, detail={"private": private})

    async def share_to_chat(self, raw: str, raw_user: str) -> ActionResult:
        user, kind, pid = self._post(raw)
        name = self._name(raw_user)

        async def act():
            await self.web.goto(wp.post_url(user, kind, pid))
            await self.web.press(SHARE)
            target = await self.web.find((f"[data-e2e='share-{name}']",), 6)
            if target is None:
                raise NotFound(f"@{name} is not in your share list, send a message first")
            await target.click(timeout=4000)
            send = await self.web.find(DIALOG_BUTTON + ("[data-floating-ui-portal] button",), 5, _word("Send"))
            if send is not None:
                await send.click(timeout=4000)

        async with self.web.lock:
            await self._guard(self.web.expect(("/im/", "/v1/message/send", "/share"), act))
        return ActionResult(action="share_to_chat", target=pid, detail={"to": name})

    async def close(self) -> None:
        await self.web.close()


class _Done(TikSocketError):
    code = "noop"
