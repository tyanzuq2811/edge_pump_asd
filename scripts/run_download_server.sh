#!/usr/bin/env bash
# ==============================================================================
# Script tự động chạy tải dữ liệu MIMII Pump trên Server Linux (nohup / tmux)
# Phục vụ đề tài NCKH Edge AI Máy Bơm 2026-2027
# ==============================================================================

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo "=========================================================="
echo "    KHỞI CHẠY TIẾN TRÌNH TẢI DỮ LIỆU MIMII PUMP TRÊN SERVER"
echo "=========================================================="
echo "Thư mục dự án: $PROJECT_DIR"

# 1. Kích hoạt môi trường ảo nếu có (venv / conda)
if [ -d "$PROJECT_DIR/venv" ]; then
    echo ">> Tìm thấy virtualenv tại $PROJECT_DIR/venv, đang kích hoạt..."
    source "$PROJECT_DIR/venv/bin/activate"
elif [ -d "$PROJECT_DIR/.venv" ]; then
    echo ">> Tìm thấy virtualenv tại $PROJECT_DIR/.venv, đang kích hoạt..."
    source "$PROJECT_DIR/.venv/bin/activate"
else
    echo ">> Không tìm thấy venv cục bộ. Đang sử dụng Python mặc định của hệ thống: $(which python3 || which python)"
fi

# 2. Tạo thư mục chứa dữ liệu và log
mkdir -p "$PROJECT_DIR/Data/raw"
mkdir -p "$PROJECT_DIR/logs"

# 3. Cài đặt các thư viện cần thiết nếu chưa có
echo ">> Kiểm tra và cài đặt thư viện từ requirements.txt..."
pip install -r requirements.txt

# 4. Tùy chọn tham số chạy:
# Mặc định: tải tất cả các mức SNR (all), tự động giải nén (--extract), ghi log vào logs/download_mimii.log
LOG_FILE="$PROJECT_DIR/logs/download_mimii.log"
PYTHON_EXEC=$(which python3 || which python)

echo ">> Đang khởi chạy tải dữ liệu ở chế độ nền (background) bằng nohup..."
echo ">> File log ghi tại: $LOG_FILE"

nohup "$PYTHON_EXEC" -u "$PROJECT_DIR/src/data/download_mimii.py" \
    --output_dir "$PROJECT_DIR/Data/raw" \
    --snr all \
    --extract \
    --log_file "$LOG_FILE" > "$LOG_FILE" 2>&1 &

PID=$!
echo "----------------------------------------------------------"
echo " ĐÃ KHỞI CHẠY TIẾN TRÌNH THÀNH CÔNG!"
echo " Mã tiến trình (PID): $PID"
echo ""
echo " Các lệnh hữu ích để theo dõi:"
echo " 1. Xem tiến trình tải thời gian thực:"
echo "    tail -f $LOG_FILE"
echo ""
echo " 2. Kiểm tra tiến trình có đang chạy:"
echo "    ps aux | grep download_mimii.py"
echo ""
echo " 3. Dừng tiến trình khi cần:"
echo "    kill $PID"
echo "----------------------------------------------------------"
