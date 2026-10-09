"""
Script tải và giải nén dữ liệu máy bơm (Pump) từ bộ dữ liệu MIMII Dataset.
Phục vụ đề tài NCKH: "Nghiên cứu và triển khai mô hình học sâu nhẹ phát hiện 
âm thanh bất thường của máy bơm trên các nền tảng Edge AI".

Zenodo Record: 3384388 (MIMII Dataset - Hitachi, Ltd.)
Bao gồm 3 tập âm thanh máy bơm theo các mức tỉ số tín hiệu trên nhiễu (SNR):
  1. -6_dB_pump.zip (~7.67 GB) - Mức nhiễu cao (-6 dB)
  2.  0_dB_pump.zip (~7.33 GB) - Mức nhiễu trung bình (0 dB)
  3.  6_dB_pump.zip (~7.13 GB) - Mức nhiễu thấp (6 dB)
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time
import zipfile
from typing import Dict, List, Optional
import requests

# Đảm bảo mã hóa UTF-8 trên Windows console
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


# Thêm thư mục gốc vào sys.path để import modules nội bộ
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.utils.logger import setup_logger

# Thông tin metadata chuẩn của các file pump từ Zenodo record 3384388
MIMII_PUMP_METADATA: Dict[str, Dict] = {
    "-6_dB": {
        "filename": "-6_dB_pump.zip",
        "size_bytes": 8236951723,
        "md5": "d20b783a0ff9c93d58f452f98c37b112",
        "urls": [
            "https://zenodo.org/records/3384388/files/-6_dB_pump.zip?download=1",
            "https://zenodo.org/api/records/3384388/files/-6_dB_pump.zip/content",
            "https://zenodo.org/record/3384388/files/-6_dB_pump.zip?download=1",
        ],
    },
    "0_dB": {
        "filename": "0_dB_pump.zip",
        "size_bytes": 7869431302,
        "md5": "488748295c3f60b25de07b58fe75b049",
        "urls": [
            "https://zenodo.org/records/3384388/files/0_dB_pump.zip?download=1",
            "https://zenodo.org/api/records/3384388/files/0_dB_pump.zip/content",
            "https://zenodo.org/record/3384388/files/0_dB_pump.zip?download=1",
        ],
    },
    "6_dB": {
        "filename": "6_dB_pump.zip",
        "size_bytes": 7659077508,
        "md5": "a09ba6060c10fc09cd4c8770213b0b9f",
        "urls": [
            "https://zenodo.org/records/3384388/files/6_dB_pump.zip?download=1",
            "https://zenodo.org/api/records/3384388/files/6_dB_pump.zip/content",
            "https://zenodo.org/record/3384388/files/6_dB_pump.zip?download=1",
        ],
    },
}

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 (MIMII-Downloader/1.0)"
)


def format_size(bytes_num: int) -> str:
    """Chuyển đổi số bytes sang định dạng người đọc (KB, MB, GB)."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(bytes_num) < 1024.0:
            return f"{bytes_num:3.2f} {unit}"
        bytes_num /= 1024.0
    return f"{bytes_num:.2f} PB"


def format_time(seconds: float) -> str:
    """Chuyển đổi số giây sang định dạng HH:MM:SS."""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:d}h {m:02d}m {s:02d}s"
    return f"{m:02d}m {s:02d}s"


def compute_md5(file_path: str, chunk_size: int = 8 * 1024 * 1024, logger=None) -> str:
    """
    Tính mã băm MD5 của một tệp lớn bằng cách đọc từng khối để tránh tràn RAM.
    """
    if logger:
        logger.info(f"Đang kiểm tra tính toàn vẹn (MD5) của {os.path.basename(file_path)}...")
    hash_md5 = hashlib.md5()
    total_size = os.path.getsize(file_path)
    processed = 0
    last_log_time = time.time()

    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hash_md5.update(chunk)
            processed += len(chunk)
            now = time.time()
            if logger and (now - last_log_time > 10):
                pct = (processed / total_size) * 100 if total_size > 0 else 0
                logger.info(f"  [MD5 check] {processed / (1024**3):.2f}/{total_size / (1024**3):.2f} GB ({pct:.1f}%)")
                last_log_time = now

    checksum = hash_md5.hexdigest()
    return checksum


def download_file_with_resume(
    url_list: List[str],
    destination_path: str,
    expected_size: Optional[int] = None,
    expected_md5: Optional[str] = None,
    chunk_size: int = 2 * 1024 * 1024,
    timeout: int = 60,
    max_retries: int = 5,
    logger=None,
) -> bool:
    """
    Tải file từ danh sách URL với tính năng HTTP Range Resume.
    Tự động tiếp tục từ vị trí đã tải nếu bị đứt mạng giữa chừng.
    """
    dest_dir = os.path.dirname(destination_path)
    if dest_dir:
        os.makedirs(dest_dir, exist_ok=True)

    filename = os.path.basename(destination_path)
    temp_file = destination_path + ".part"

    # Kiểm tra nếu file đích hoàn chỉnh đã tồn tại
    if os.path.exists(destination_path):
        current_size = os.path.getsize(destination_path)
        if expected_size and current_size == expected_size:
            if logger:
                logger.info(f"File {filename} đã tồn tại đầy đủ ({format_size(current_size)}).")
            if expected_md5:
                actual_md5 = compute_md5(destination_path, logger=logger)
                if actual_md5.lower() == expected_md5.lower():
                    if logger:
                        logger.info(f"Xác thực MD5 khớp chính xác! Bỏ qua tải.")
                    return True
                else:
                    if logger:
                        logger.warning(
                            f"MD5 không khớp! Dự kiến: {expected_md5}, thực tế: {actual_md5}. "
                            f"Sẽ tải lại file."
                        )
                    os.remove(destination_path)
            else:
                return True

    # Thử lần lượt các URL mirror
    for url_idx, url in enumerate(url_list):
        if logger:
            logger.info(f"Bắt đầu tải từ nguồn {url_idx + 1}/{len(url_list)}: {url}")

        retry_count = 0
        while retry_count < max_retries:
            try:
                # Kiểm tra dung lượng hiện có của file tạm để resume
                existing_bytes = 0
                if os.path.exists(temp_file):
                    existing_bytes = os.path.getsize(temp_file)
                    if expected_size and existing_bytes > expected_size:
                        if logger:
                            logger.warning("File tạm lớn hơn kích thước dự kiến. Xóa tải lại.")
                        os.remove(temp_file)
                        existing_bytes = 0

                headers = {"User-Agent": DEFAULT_USER_AGENT}
                if existing_bytes > 0:
                    headers["Range"] = f"bytes={existing_bytes}-"
                    if logger:
                        logger.info(f"Tiếp tục tải (Resume) từ vị trí: {format_size(existing_bytes)}")

                session = requests.Session()
                response = session.get(url, headers=headers, stream=True, timeout=timeout)

                # Trường hợp resume thành công (206 Partial Content)
                if response.status_code == 206:
                    write_mode = "ab"
                    downloaded_so_far = existing_bytes
                    total_file_size = expected_size or (
                        int(response.headers.get("Content-Length", 0)) + existing_bytes
                    )
                # Trường hợp tải mới hoặc server không hỗ trợ 206 (200 OK)
                elif response.status_code == 200:
                    write_mode = "wb"
                    downloaded_so_far = 0
                    total_file_size = int(response.headers.get("Content-Length", expected_size or 0))
                # Trường hợp file đã tải trọn vẹn (416 Range Not Satisfiable)
                elif response.status_code == 416:
                    if logger:
                        logger.info("Server báo Range Not Satisfiable (file đã hoàn thành).")
                    if os.path.exists(temp_file):
                        shutil.move(temp_file, destination_path)
                        return True
                    break
                elif response.status_code == 403:
                    if logger:
                        logger.warning(f"Zenodo trả về mã lỗi 403 Forbidden đối với URL: {url}")
                    break
                else:
                    response.raise_for_status()

                is_tty = sys.stdout.isatty()
                start_time = time.time()
                last_log_time = start_time
                bytes_since_last_log = 0

                if logger:
                    logger.info(
                        f"Đang tải {filename} (Tổng: {format_size(total_file_size)}, "
                        f"còn lại: {format_size(total_file_size - downloaded_so_far)})..."
                    )

                with open(temp_file, write_mode) as f:
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if not chunk:
                            continue
                        f.write(chunk)
                        chunk_len = len(chunk)
                        downloaded_so_far += chunk_len
                        bytes_since_last_log += chunk_len

                        now = time.time()
                        # Trong môi trường nohup (không có TTY), in định kỳ 10 giây một lần để log gọn gàng
                        # Trong terminal tương tác (TTY), in tiến trình mỗi 1.5 giây
                        log_interval = 1.5 if is_tty else 10.0
                        if now - last_log_time >= log_interval:
                            duration = now - last_log_time
                            speed = bytes_since_last_log / duration if duration > 0 else 0
                            pct = (downloaded_so_far / total_file_size * 100) if total_file_size > 0 else 0
                            remaining_bytes = total_file_size - downloaded_so_far
                            eta_sec = (remaining_bytes / speed) if speed > 0 else 0

                            msg = (
                                f"  [{filename}] {pct:5.1f}% | "
                                f"{format_size(downloaded_so_far)} / {format_size(total_file_size)} | "
                                f"{format_size(speed)}/s | ETA: {format_time(eta_sec)}"
                            )
                            if is_tty:
                                print(f"\r{msg}", end="", flush=True)
                            else:
                                if logger:
                                    logger.info(msg)

                            last_log_time = now
                            bytes_since_last_log = 0

                if is_tty:
                    print()  # Xuống dòng sau khi hoàn tất

                # Đổi tên file tạm thành file chính thức sau khi tải xong
                if os.path.exists(temp_file):
                    shutil.move(temp_file, destination_path)
                    if logger:
                        logger.info(f"Đã tải xong tệp: {filename} ({format_size(os.path.getsize(destination_path))})")

                # Kiểm tra MD5
                if expected_md5:
                    actual_md5 = compute_md5(destination_path, logger=logger)
                    if actual_md5.lower() == expected_md5.lower():
                        if logger:
                            logger.info(f"Xác thực MD5 thành công cho {filename}!")
                        return True
                    else:
                        if logger:
                            logger.error(
                                f"LỖI: MD5 không khớp! Dự kiến: {expected_md5}, nhận được: {actual_md5}"
                            )
                        if os.path.exists(destination_path):
                            os.remove(destination_path)
                        retry_count += 1
                        continue

                return True

            except (requests.RequestException, IOError) as e:
                retry_count += 1
                if logger:
                    logger.warning(f"Lỗi kết nối ({e}). Thử lại lần {retry_count}/{max_retries} sau 5 giây...")
                time.sleep(5)

    if logger:
        logger.error(f"Không thể tải hoàn tất tệp: {filename}")
    return False


def extract_zip_file(zip_path: str, extract_to: str, delete_zip: bool = False, logger=None) -> bool:
    """
    Giải nén file zip chứa dữ liệu máy bơm vào thư mục đích.
    Hiển thị tiến độ và số lượng tệp được giải nén.
    """
    if not os.path.exists(zip_path):
        if logger:
            logger.error(f"Không tìm thấy file để giải nén: {zip_path}")
        return False

    os.makedirs(extract_to, exist_ok=True)
    filename = os.path.basename(zip_path)

    if logger:
        logger.info(f"Bắt đầu giải nén {filename} -> {extract_to}...")

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            members = zf.namelist()
            total_members = len(members)
            if logger:
                logger.info(f"Tổng số tệp âm thanh trong lưu trữ: {total_members}")

            last_log_time = time.time()
            for idx, member in enumerate(members):
                zf.extract(member, path=extract_to)
                now = time.time()
                if logger and (now - last_log_time > 15):
                    pct = (idx + 1) / total_members * 100
                    logger.info(f"  [Giải nén {filename}] Đã giải nén {idx + 1}/{total_members} files ({pct:.1f}%)")
                    last_log_time = now

        if logger:
            logger.info(f"Giải nén thành công {filename}!")

        if delete_zip:
            if logger:
                logger.info(f"Đang xóa file zip {filename} để giải phóng dung lượng ổ đĩa...")
            os.remove(zip_path)

        return True
    except Exception as e:
        if logger:
            logger.error(f"Lỗi trong quá trình giải nén {filename}: {e}")
        return False


def download_mimii_pump(
    output_dir: str = "./Data/raw",
    snr_filter: str = "all",
    extract: bool = False,
    delete_zip: bool = False,
    skip_checksum: bool = False,
    logger=None,
) -> bool:
    """
    Hàm tổng điều phối việc tải và chuẩn bị dữ liệu máy bơm từ MIMII Dataset.
    """
    if logger is None:
        logger = setup_logger("MIMII_Pump_Downloader")

    os.makedirs(output_dir, exist_ok=True)

    keys_to_download = []
    if snr_filter.lower() == "all":
        keys_to_download = list(MIMII_PUMP_METADATA.keys())
    elif snr_filter in MIMII_PUMP_METADATA:
        keys_to_download = [snr_filter]
    else:
        logger.error(f"Mức SNR không hợp lệ: '{snr_filter}'. Chọn một trong: all, -6_dB, 0_dB, 6_dB.")
        return False

    logger.info("=" * 70)
    logger.info("   BẮT ĐẦU QUÁ TRÌNH TẢI BỘ DỮ LIỆU MÁY BƠM (MIMII PUMP DATASET)")
    logger.info(f"   Thư mục lưu trữ  : {os.path.abspath(output_dir)}")
    logger.info(f"   Các mức SNR chọn : {', '.join(keys_to_download)}")
    logger.info(f"   Tự động giải nén : {'BẬT' if extract else 'TẮT'}")
    logger.info(f"   Xóa file zip sau giải nén: {'BẬT' if delete_zip else 'TẮT'}")
    logger.info("=" * 70)

    success_all = True
    for snr_key in keys_to_download:
        meta = MIMII_PUMP_METADATA[snr_key]
        dest_file = os.path.join(output_dir, meta["filename"])

        logger.info(f"\n>>> [1/2] Xử lý tập {meta['filename']} ({snr_key}) - Dung lượng: {format_size(meta['size_bytes'])}")

        expected_md5 = None if skip_checksum else meta["md5"]
        download_ok = download_file_with_resume(
            url_list=meta["urls"],
            destination_path=dest_file,
            expected_size=meta["size_bytes"],
            expected_md5=expected_md5,
            logger=logger,
        )

        if not download_ok:
            logger.error(f"Thất bại khi tải {meta['filename']}!")
            success_all = False
            continue

        if extract:
            logger.info(f">>> [2/2] Bắt đầu giải nén {meta['filename']}...")
            extract_dest = os.path.join(output_dir, "pump")
            extract_ok = extract_zip_file(
                zip_path=dest_file,
                extract_to=extract_dest,
                delete_zip=delete_zip,
                logger=logger,
            )
            if not extract_ok:
                logger.error(f"Thất bại khi giải nén {meta['filename']}!")
                success_all = False

    logger.info("\n" + "=" * 70)
    if success_all:
        logger.info(" HOÀN TẤT: Toàn bộ dữ liệu máy bơm đã được chuẩn bị thành công!")
    else:
        logger.warning(" KẾT THÚC CÓ CẢNH BÁO: Một số tệp tải hoặc giải nén gặp sự cố.")
    logger.info("=" * 70)

    return success_all


def parse_args():
    parser = argparse.ArgumentParser(
        description="Tải và quản lý tập dữ liệu âm thanh máy bơm (Pump) từ MIMII Dataset (Zenodo 3384388)."
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default="./Data/raw",
        help="Đường dẫn thư mục lưu trữ dữ liệu tải về (Mặc định: ./Data/raw)",
    )
    parser.add_argument(
        "--snr",
        type=str,
        default="all",
        choices=["all", "-6_dB", "0_dB", "6_dB"],
        help="Mức tỉ số tín hiệu trên nhiễu (SNR) cần tải (Mặc định: all - tải cả 3 mức)",
    )
    parser.add_argument(
        "--extract",
        action="store_true",
        help="Tự động giải nén file zip sau khi tải xong.",
    )
    parser.add_argument(
        "--delete_zip",
        action="store_true",
        help="Xóa file zip gốc sau khi giải nén thành công để tiết kiệm dung lượng ổ cứng.",
    )
    parser.add_argument(
        "--skip_checksum",
        action="store_true",
        help="Bỏ qua bước kiểm tra mã MD5 (không khuyến nghị).",
    )
    parser.add_argument(
        "--log_file",
        type=str,
        default="./logs/download_mimii.log",
        help="Đường dẫn file ghi log (Mặc định: ./logs/download_mimii.log)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    logger = setup_logger("MIMII_Downloader", log_file=args.log_file)
    download_mimii_pump(
        output_dir=args.output_dir,
        snr_filter=args.snr,
        extract=args.extract,
        delete_zip=args.delete_zip,
        skip_checksum=args.skip_checksum,
        logger=logger,
    )


if __name__ == "__main__":
    main()
