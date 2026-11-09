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
