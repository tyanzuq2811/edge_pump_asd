#!/usr/bin/env bash
# ==============================================================================
# Script tải dữ liệu MIMII Pump trực tiếp bằng curl (hỗ trợ Resume và chống 403)
# ==============================================================================

set -e

DATA_DIR="${1:-/hdd3/users/dunglt/edge_pump_asd/data}"
mkdir -p "$DATA_DIR"
cd "$DATA_DIR"

echo "=========================================================="
echo "   TẢI DỮ LIỆU MÁY BƠM (MIMII PUMP) TRỰC TIẾP BẰNG CURL"
echo "=========================================================="
echo "Thư mục lưu dữ liệu: $DATA_DIR"
echo ""

# Danh sách 3 file zip của máy bơm từ Zenodo record 3384388
FILES=("6_dB_pump.zip" "0_dB_pump.zip" "-6_dB_pump.zip")

USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
REFERER="https://zenodo.org/records/3384388"

for f in "${FILES[@]}"; do
    echo "----------------------------------------------------------"
    echo ">> [1/2] Đang tải / tiếp tục tải (Resume): $f ..."
    echo "----------------------------------------------------------"

    URL="https://zenodo.org/records/3384388/files/${f}?download=1"

    # curl:
    #   -C -         : Tự động tiếp tục từ byte đã tải dở (Resume)
    #   -L           : Tự động theo dõi chuyển hướng (Redirects)
    #   -A           : Giả lập trình duyệt chuẩn để vượt qua WAF/Cloudflare
    #   -H           : Header Referer chính thức từ Zenodo records 3384388
    #   --retry 10   : Tự động thử lại 10 lần nếu mạng đứt
    curl -C - -L \
        -A "$USER_AGENT" \
        -H "Referer: $REFERER" \
        -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" \
        -H "Accept-Language: en-US,en;q=0.9" \
        --connect-timeout 60 \
        --retry 10 \
        --retry-delay 5 \
        "$URL" \
        -o "$f"

    echo ""
    echo ">> [2/2] Đang giải nén $f (tự động bỏ qua file đã có)..."
    if command -v unzip >/dev/null 2>&1; then
        unzip -n -q "$f"
    elif command -v 7z >/dev/null 2>&1; then
        7z x -aos "$f"
    else
        python3 -c "import zipfile, os; zf=zipfile.ZipFile('$f'); zf.extractall('.')"
    fi
    echo ">> Hoàn tất xử lý tệp $f!"
    echo ""
done

echo "=========================================================="
echo " HOÀN TẤT TOÀN BỘ: Dữ liệu đã sẵn sàng tại $DATA_DIR!"
echo "=========================================================="
