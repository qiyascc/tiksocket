#!/usr/bin/env sh
TOKEN=${TOKEN:-change-me}
BASE=http://127.0.0.1:8787/api/accounts/main

curl -s -X POST -H "Authorization: Bearer $TOKEN" "$BASE/login/qr"
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/login"
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/chats"
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"text": "Hello from TikSocket", "client_id": "hello-1"}' "$BASE/chats/0:1:111:222/messages"
curl -s -X POST -H "Authorization: Bearer $TOKEN" -F kind=photos -F caption="Hi" -F sound="lofi" \
  -F file=@a.jpg -F file=@b.jpg "$BASE/posts"
curl -N -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8787/api/events

curl -s -H "Authorization: Bearer $TOKEN" "$BASE/users/tiktok"
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/users/tiktok/followers?count=20"
curl -s -X POST -H "Authorization: Bearer $TOKEN" "$BASE/users/tiktok/follow"
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/search/users?q=real%20estate"
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/post?post=https://www.tiktok.com/@user/video/7600000000000000000"
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"post": "https://www.tiktok.com/@user/video/7600000000000000000"}' "$BASE/post/like"
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"post": "https://www.tiktok.com/@user/video/7600000000000000000", "text": "Great view"}' "$BASE/post/comment"
curl -s -X PATCH -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"bio": "Open 9 to 6"}' "$BASE/profile"
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/feed?kind=explore&count=5"
curl -s -H "Authorization: Bearer $TOKEN" "$BASE/notifications?kind=comment"
