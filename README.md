# Nghiên Cứu và Triển Khai Mô Hình Học Sâu Nhẹ Phát Hiện Âm Thanh Bất Thường Của Máy Bơm Trên Các Nền Tảng Edge AI

**Đề tài Nghiên cứu Khoa học Sinh viên (Năm học 2026 - 2027)**  
*Trường Đại học Đại Nam - Khoa Công nghệ Thông tin*  
- **Chủ nhiệm đề tài:** Lê Tuấn Dũng (MSSV: 1771020189)
- **Cán bộ hướng dẫn:** ThS. Lê Thái Bảo

---

## 1. Cấu Trúc Thư Mục Dự Án

```text
Pump/
├── docs/                             # Tài liệu đề cương (đã được .gitignore bỏ qua)
├── src/                              # Mã nguồn chính
│   ├── __init__.py
│   ├── data/                         # Module tải, kiểm tra và giải nén dữ liệu
│   │   ├── __init__.py
│   │   └── download_mimii.py         # Script tải dữ liệu máy bơm từ Zenodo MIMII
│   ├── features/                     # Module trích xuất đặc trưng (MFCC, Mel-spec)
│   ├── models/                       # Mô hình học sâu nhẹ (CNN, MobileNet, Autoencoder)
│   └── utils/                        # Tiện ích logging, cấu hình, helper
│       ├── __init__.py
│       └── logger.py                 # Logger hỗ trợ auto-flush cho nohup/tmux
├── scripts/                          # Script chạy tự động trên Server
│   └── run_download_server.sh        # Bash script chạy ngầm trên Linux Server
├── Data/                             # Thư mục chứa dữ liệu (đã được .gitignore bỏ qua)
│   ├── raw/                          # File nén zip và file âm thanh wav gốc
│   └── processed/                    # File đặc trưng đã tiền xử lý (.npy)
├── logs/                             # File nhật ký hoạt động (log files)
├── .gitignore                        # Loại bỏ file nặng/nhị phân khỏi Git
├── requirements.txt                  # Danh sách thư viện cần thiết
└── README.md                         # Hướng dẫn chi tiết dự án
```

---

## 2. Thông Tin Tập Dữ Liệu Máy Bơm (MIMII Pump Dataset)

Dữ liệu được tải từ nguồn chính thức của **Hitachi, Ltd.** trên **Zenodo** (Record ID: `3384388`).
Dữ liệu chỉ trích xuất riêng cho **Máy bơm (Pump)** bao gồm 3 tập theo mức độ nhiễu SNR (Signal-to-Noise Ratio):

| Tập dữ liệu | Kích thước nén | Mã băm MD5 | Mức nhiễu | Ghi chú |
| :--- | :---: | :---: | :---: | :--- |
| `6_dB_pump.zip` | ~7.13 GB | `a09ba6060c10fc09cd4c8770213b0b9f` | Nhiễu thấp (sạch) | Tiếng bơm to hơn tiếng ồn 6 dB |
| `0_dB_pump.zip` | ~7.33 GB | `488748295c3f60b25de07b58fe75b049` | Nhiễu vừa | Tiếng bơm ngang tiếng ồn nền |
| `-6_dB_pump.zip` | ~7.67 GB | `d20b783a0ff9c93d58f452f98c37b112` | Nhiễu nặng | Tiếng ồn nền át tiếng bơm 6 dB |
| **Tổng cộng** | **~22.13 GB** | - | - | **4 máy bơm (`id_00`, `02`, `04`, `06`)** |

Mỗi máy bơm có các bản ghi âm đa kênh (8 kênh mic, 16 kHz, định dạng WAV, thời lượng 10 giây/file) chia thành 2 trạng thái:
- `normal/`: Âm thanh hoạt động bình thường.
- `abnormal/`: Âm thanh gặp sự cố/bất thường (rò rỉ, kẹt cánh bơm, mất tải, hỏng bạc đạn).

---

## 3. Quy Trình 1: Đẩy Mã Nguồn Từ Máy Local Lên Git

Mở Terminal (hoặc PowerShell) tại thư mục `Pump` trên máy tính local của bạn và chạy các lệnh sau:

```bash
# 1. Khởi tạo Git repository (nếu chưa khởi tạo)
git init

# 2. Thêm tất cả các file mã nguồn (file .gitignore sẽ tự động loại trừ thư mục Data/ và các file nặng)
git add .

# 3. Commit phiên bản đầu tiên
git commit -m "feat: init project structure and MIMII pump dataset downloader"

# 4. Đổi tên nhánh chính thành main
git branch -M main

# 5. Liên kết với remote repository trên GitHub / GitLab (thay link repo của bạn vào đây)
git remote add origin https://github.com/<tai-khoan-cua-ban>/<ten-repo>.git

# 6. Đẩy code lên GitHub
git push -u origin main
```

---

## 4. Quy Trình 2: Thiết Lập Trên Server

Đăng nhập SSH vào Server của bạn và thực hiện các bước sau:

```bash
# 1. Clone dự án về Server
git clone https://github.com/<tai-khoan-cua-ban>/<ten-repo>.git
cd <ten-repo>

# 2. Tạo môi trường ảo Python (khuyến nghị để tránh xung đột thư viện hệ thống)
python3 -m venv venv
source venv/bin/activate

# 3. Nâng cấp pip và cài đặt các thư viện cần thiết
pip install --upgrade pip
pip install -r requirements.txt
```

---

## 5. Quy Trình 3: Chạy Tải Dữ Liệu Ngầm Trên Server

Do dung lượng dữ liệu lớn (~22.1 GB), bạn nên chạy ngầm để không bị gián đoạn khi tắt máy tính local hoặc ngắt kết nối SSH.

### Cách 1: Sử dụng `tmux` (Khuyến nghị - Dễ quản lý và trực quan nhất)

```bash
# 1. Tạo một phiên tmux mới tên là 'mimii_pump'
tmux new -s mimii_pump

# 2. Kích hoạt môi trường ảo (nếu chưa kích hoạt)
source venv/bin/activate

# 3. Chạy script tải và tự động giải nén (mặc định script sẽ tự nhận diện lưu vào /hdd3/users/dunglt/edge_pump_asd/data)
python src/data/download_mimii.py --output_dir /hdd3/users/dunglt/edge_pump_asd/data --snr all --extract

# 4. Rời khỏi tmux (Detach):
#    Nhấn tổ hợp phím: Ctrl + B, sau đó nhấn phím D
#    (Tiến trình vẫn tiếp tục chạy ngầm trên server ngay cả khi bạn tắt SSH!)

# 5. Khi nào muốn quay lại xem tiến trình:
tmux attach -t mimii_pump

# 6. Thoát hẳn và xóa phiên tmux khi tải xong: gõ exit
```

---

### Cách 2: Sử dụng `nohup`

```bash
# Cách 2.1: Dùng script tự động đã cấu hình sẵn đường dẫn /hdd3/users/dunglt/edge_pump_asd/data
chmod +x scripts/run_download_server.sh
./scripts/run_download_server.sh

# Hoặc cách 2.2: Chạy trực tiếp lệnh nohup
nohup python -u src/data/download_mimii.py \
    --output_dir /hdd3/users/dunglt/edge_pump_asd/data \
    --snr all \
    --extract \
    --log_file ./logs/download_mimii.log > ./logs/download_mimii.log 2>&1 &
```

**Cách quản lý và theo dõi tiến trình `nohup`:**
```bash
# Xem nhật ký tải theo thời gian thực (nhấn Ctrl + C để dừng xem):
tail -f logs/download_mimii.log

# Kiểm tra xem tiến trình Python có đang chạy không:
ps aux | grep download_mimii.py

# Nếu muốn hủy/dừng tiến trình tải:
kill <PID_của_tiến_trình>
```

---

## 6. Các Tham Số Tùy Chọn Của Script `download_mimii.py`

| Tham số | Giá trị mặc định | Giải thích |
| :--- | :---: | :--- |
| `--output_dir` | `./Data/raw` | Thư mục lưu file zip và dữ liệu |
| `--snr` | `all` | Lựa chọn mức nhiễu: `all`, `-6_dB`, `0_dB`, `6_dB` |
| `--extract` | `False` | Tự động giải nén sau khi tải xong |
| `--delete_zip` | `False` | Tự động xóa file `.zip` sau khi giải nén xong để tiết kiệm ổ cứng |
| `--skip_checksum` | `False` | Bỏ qua bước kiểm tra mã MD5 |
| `--log_file` | `./logs/download_mimii.log` | Đường dẫn file lưu nhật ký |

**Ví dụ:**
```bash
# Chỉ tải tập 6_dB (nhiễu thấp nhất) để thử nghiệm trước và tự động giải nén:
python src/data/download_mimii.py --snr 6_dB --extract

# Tải tất cả các tập, giải nén và tự động xóa các file zip gốc để tiết kiệm 22GB ổ cứng:
python src/data/download_mimii.py --snr all --extract --delete_zip
```

---

## 7. Các Tính Năng Kỹ Thuật Nổi Bật Của Bộ Tải
1. **HTTP Range Resume**: Nếu mạng chập chờn hoặc rớt kết nối ở GB thứ 5, khi chạy lại script sẽ tự động tải tiếp từ 5 GB, không cần tải lại từ đầu.
2. **MD5 Checksum Verification**: Xác thực tính toàn vẹn của từng file zip theo đúng mã băm chính thức từ Zenodo để đảm bảo không bị lỗi dữ liệu âm thanh.
3. **Flush Buffer Real-time**: Luôn xả bộ nhớ đệm (buffer flush) để lệnh `tail -f` hiển thị tiến độ tức thì ngay cả khi chạy qua `nohup`.
4. **Phát hiện TTY thông minh**: Tự động giảm tần suất in nhật ký khi chạy nền (non-interactive) để tránh tràn file log, nhưng vẫn hiển thị thanh tiến trình mượt mà khi chạy trong terminal tương tác (`tmux`).
