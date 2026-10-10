#!/usr/bin/env bash
# ==============================================================================
# Script tải dữ liệu MIMII Pump trực tiếp bằng curl
# Đã xử lý tiền tố ./ cho file bắt đầu bằng dấu trừ (-6_dB_pump.zip)
# ==============================================================================

DATA_DIR="${1:-/hdd3/users/dunglt/edge_pump_asd/data}"
mkdir -p "$DATA_DIR"
cd "$DATA_DIR"

echo "=========================================================="
echo "   TẢI DỮ LIỆU MÁY BƠM (MIMII PUMP) TRỰC TIẾP BẰNG CURL"
echo "=========================================================="
echo "Thư mục lưu dữ liệu: $DATA_DIR"
echo ""

# Danh sách 3 file (dùng tiền tố ./ để tránh Linux hiểu nhầm dấu '-' là cờ lệnh)
FILES=("6_dB_pump.zip" "0_dB_pump.zip" "-6_dB_pump.zip")
declare -A SIZES
SIZES["6_dB_pump.zip"]=7659077508
SIZES["0_dB_pump.zip"]=7869431302
SIZES["-6_dB_pump.zip"]=8236951723

USER_AGENT="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
REFERER="https://zenodo.org/records/3384388"

format_bytes() {
    local b=$1
    if [ "$b" -gt 1073741824 ]; then
        echo "$(awk "BEGIN {printf \"%.2f GB\", $b/1073741824}")"
    elif [ "$b" -gt 1048576 ]; then
        echo "$(awk "BEGIN {printf \"%.2f MB\", $b/1048576}")"
    else
        echo "$b bytes"
    fi
}

get_file_size() {
    local file="./$1"
    if [ -f "$file" ]; then
        stat -c%s -- "$file" 2>/dev/null || stat -f%z -- "$file" 2>/dev/null || wc -c < "$file" 2>/dev/null || echo 0
    else
        echo 0
    fi
}

for f in "${FILES[@]}"; do
    FILE_PATH="./$f"
    EXPECTED_SIZE=${SIZES[$f]}
    URL="https://zenodo.org/records/3384388/files/${f}?download=1"

    echo "=========================================================="
    echo ">> XỬ LÝ: $f (Dung lượng chuẩn: $(format_bytes "$EXPECTED_SIZE"))"
    echo "=========================================================="

    CURRENT_SIZE=$(get_file_size "$f")

    # VÒNG LẶP AUTO-RETRY: Tự động tải tiếp nếu mạng bị rớt
    RETRY_COUNT=1
    while [ "$CURRENT_SIZE" -lt "$EXPECTED_SIZE" ]; do
        PCT=$(awk "BEGIN {printf \"%.1f\", ($CURRENT_SIZE/$EXPECTED_SIZE)*100}")
        echo ">> [Lần $RETRY_COUNT] Đang tải tiếp từ vị trí: $(format_bytes "$CURRENT_SIZE") / $(format_bytes "$EXPECTED_SIZE") ($PCT%)..."

        # Chạy curl với resume (-C -) và file đích có tiền tố ./
        curl -C - -L \
            -A "$USER_AGENT" \
            -H "Referer: $REFERER" \
            -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" \
            -H "Accept-Language: en-US,en;q=0.9" \
            --connect-timeout 60 \
            "$URL" \
            -o "$FILE_PATH" || true

        NEW_SIZE=$(get_file_size "$f")

        if [ "$NEW_SIZE" -ge "$EXPECTED_SIZE" ]; then
            echo ""
            echo ">> HOÀN THÀNH 100%: Đã tải trọn vẹn $f ($(format_bytes "$NEW_SIZE"))!"
            break
        fi

        if [ "$NEW_SIZE" -gt "$CURRENT_SIZE" ]; then
            GAINED=$((NEW_SIZE - CURRENT_SIZE))
            echo ""
            echo "⚡ [KẾT NỐI NGẮT] Đã tải thêm được: $(format_bytes "$GAINED")."
            echo ">> Tự động kết nối lại sau 3 giây để tải tiếp phần còn lại..."
        else
            echo ""
            echo "⚠️ [CHƯA TẢI THÊM ĐƯỢC] Chờ 5 giây và thử lại..."
            sleep 2
        fi

        CURRENT_SIZE=$NEW_SIZE
        RETRY_COUNT=$((RETRY_COUNT + 1))
        sleep 3
    done

    # Chỉ giải nén khi file đã đủ 100% dung lượng
    FINAL_SIZE=$(get_file_size "$f")
    SNR_NAME="${f%_pump.zip}"
    mkdir -p "./$SNR_NAME"
    echo ""
    echo ">> BẮT ĐẦU GIẢI NÉN $f vào thư mục ./$SNR_NAME (tự động bỏ qua file đã có)..."
    if command -v unzip >/dev/null 2>&1; then
        unzip -n -q "$FILE_PATH" -d "./$SNR_NAME"
    elif command -v 7z >/dev/null 2>&1; then
        7z x -aos "$FILE_PATH" -o"./$SNR_NAME"
    else
        python3 -c "import zipfile; zf=zipfile.ZipFile('$FILE_PATH'); zf.extractall('./$SNR_NAME')"
    fi
    echo ">> GIẢI NÉN HOÀN TẤT CHO $f vào ./$SNR_NAME!"
        echo ""
    else
        echo "⚠️ CẢNH BÁO: Tệp $f chưa hoàn chỉnh ($(format_bytes "$FINAL_SIZE") / $(format_bytes "$EXPECTED_SIZE")). Chưa giải nén."
    fi
done

echo "=========================================================="
echo " HOÀN TẤT TOÀN BỘ CÁC TẬP MÁY BƠM TẠI: $DATA_DIR!"
echo "=========================================================="
