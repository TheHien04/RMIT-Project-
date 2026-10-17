# RMIT Voice Coach — ADC 2026

Trợ lý onboarding bằng giọng nói tiếng Việt cho người khiếm thị. Coach đọc
lesson đã duyệt, quan sát trang bằng DOM/accessibility tree, và chỉ dùng
screenshot opt-in khi DOM không đủ. Người học vẫn tự Tab/Enter; completion luôn
được xác minh local.

Hướng dẫn chạy và privacy boundary nằm tại [`coach/README.md`](coach/README.md).

## Cấu trúc repository

```text
.
├── coach/
│   ├── app_launcher/        source của launcher macOS
│   ├── control_app/         giao diện điều khiển local
│   ├── demo/                kịch bản trình diễn
│   ├── docs/                kiến trúc, UX và hướng dẫn kiểm thử
│   ├── fixtures/            lesson và website test đã review, tách theo loại
│   ├── sandbox/             website test accessibility cục bộ
│   ├── scripts/             script build và khởi động Chrome riêng
│   ├── src/coach/           mã nguồn Python
│   └── tests/               unit, integration và browser tests
└── README.md
```

Các model cache, virtual environment, log, tiến độ, app bundle đã build và các
repository tham khảo cục bộ đều bị loại khỏi Git. Xem
[`coach/docs/README.md`](coach/docs/README.md) để bắt đầu đọc tài liệu.
