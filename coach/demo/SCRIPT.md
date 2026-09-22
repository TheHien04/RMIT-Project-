# Kịch bản demo

## Sandbox div-only

Chạy `.venv312/bin/python -m coach live` khi `.env` chưa có CDP target.

1. Nói “bắt đầu học”.
2. Coach đọc bước 1 và bật coach-list cho sandbox.
3. ArrowDown nghe “Tạo bảng. Enter.”, rồi tự Enter.
4. ArrowDown tới “Thêm cột”, Enter hai lần để tạo `Ca` và `Người`.
5. ArrowDown tới “Lưu bảng”, Enter.
6. Coach xác minh DOM local rồi nói hoàn thành một lần và tự dừng.

## Supabase staging

1. Chạy `sh scripts/launch_coach_chrome.sh`.
2. Người học tự login Supabase staging trong Chrome profile riêng.
3. Đặt CDP/origin/PDF/manifest trong `.env`, rồi chạy coach.
4. Nói “bắt đầu học”.
5. Dùng Tab/Shift+Tab hoặc screen reader; coach không cướp arrow keys.
6. Người học tự Enter control; coach xác minh URL/text/focus local trước khi chuyển bước.

Không demo SQL execution, API key, billing, account/member settings hay thao tác
destructive. “focus giúp”/“bấm giúp” là assist explicit và được audit local.
