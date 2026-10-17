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
5. Dùng Tab/Shift+Tab tới `Table Editor`, rồi tự nhấn Enter.
6. Ở vùng nội dung chính, tiếp tục Tab tới `Create a table`. Nếu website không
   cho target này nhận focus, coach thông báo đã sửa keyboard cho đúng target;
   người học vẫn tự Tab và tự nhấn Enter.
7. Coach chỉ chuyển bước khi thấy trường `Name` của biểu mẫu tạo bảng xuất hiện.
   Việc chỉ focus vào `Create a table` chưa được tính là hoàn thành.
8. Tại `Name`, nhập `coach_demo_tasks`, rồi tiếp tục Tab. Giữ RLS và hai cột mặc
   định `id`, `created_at`.
9. Khi coach nói “Đã tới Save”, kiểm tra tên bảng rồi người học tự nhấn Enter.
   Coach không nhận lệnh “bấm giúp” ở bước này vì Save ghi schema thật.
10. Bài chỉ hoàn thành khi URL chuyển sang route của bảng vừa tạo.
11. Nói `gợi ý` từng lần để kiểm tra hint ladder; nói `tôi đang ở đâu` để nghe vị
   trí focus hiện tại.

Không demo SQL execution, API key, billing, account/member settings hay thao tác
destructive ngoài việc tạo bảng staging đã nêu rõ. “focus giúp”/“bấm giúp” là
assist explicit và được audit local; synthetic click luôn bị khóa ở bước destructive.
