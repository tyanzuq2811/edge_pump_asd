"""
Script tải và giải nén dữ liệu máy bơm (Pump) từ bộ dữ liệu MIMII Dataset.
Phục vụ đề tài NCKH: "Nghiên cứu và triển khai mô hình học sâu nhẹ phát hiện 
âm thanh bất thường của máy bơm trên các nền tảng Edge AI".

Hỗ trợ cơ chế chịu lỗi (Fault-Tolerant & Auto-Resume):
  - Tiếp tục tải từ điểm bị ngắt nếu tiến trình bị kill (kill, pkill, kill -9).
  - Tự động bỏ qua các tập SNR hoặc các file đã tải/giải nén hoàn thành.
  - Cơ chế ghi trực tiếp xuống ổ cứng (fsync) định kỳ để không mất dữ liệu.
  - Quản lý checkpoint trạng thái (.download_checkpoint.json).
"""

import argparse
import hashlib
import json
import os
import shutil
import signal
import sys
import time
import zipfile
from typing import Dict, List, Optional, Tuple
import requests

# Đảm bảo mã hóa UTF-8 trên console
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

# Biến toàn cục phục vụ xử lý tín hiệu ngắt (Signal handler)
CURRENT_FILE_HANDLE = None
CURRENT_LOGGER = None


def register_signal_handler():
    """Bắt các tín hiệu ngắt tiến trình (SIGINT, SIGTERM) để flush dữ liệu an toàn trước khi dừng."""
    def _handler(signum, frame):
        global CURRENT_FILE_HANDLE, CURRENT_LOGGER
        sig_name = "SIGTERM" if signum == signal.SIGTERM else ("SIGINT" if signum == signal.SIGINT else str(signum))
        if CURRENT_FILE_HANDLE and not CURRENT_FILE_HANDLE.closed:
            try:
                CURRENT_FILE_HANDLE.flush()
                os.fsync(CURRENT_FILE_HANDLE.fileno())
            except Exception:
                pass

        if CURRENT_LOGGER:
            CURRENT_LOGGER.warning(
                f"\n[NGẮT TIẾN TRÌNH] Nhận tín hiệu {sig_name} (tiến trình bị kill hoặc dừng). "
                f"Đã lưu an toàn toàn bộ dữ liệu đã đào xuống đĩa! "
                f"Khi khởi chạy lại, hệ thống sẽ tự động đào tiếp tục từ điểm này."
            )
        sys.exit(0)

    try:
        signal.signal(signal.SIGINT, _handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _handler)
    except Exception:
        pass


class DownloadCheckpoint:
    """Quản lý tệp lưu trạng thái (.download_checkpoint.json) để ghi nhớ tiến độ đào dữ liệu."""
    def __init__(self, output_dir: str):
        self.checkpoint_path = os.path.join(output_dir, ".download_checkpoint.json")
        self.data = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.checkpoint_path):
            try:
                with open(self.checkpoint_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save(self, snr: str, status: str, details: Optional[dict] = None):
        if snr not in self.data:
            self.data[snr] = {}
        self.data[snr].update({
            "status": status,
            "last_updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            **(details or {})
        })
        try:
            with open(self.checkpoint_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def get_status(self, snr: str) -> str:
        return self.data.get(snr, {}).get("status", "pending")


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
    """Tính mã băm MD5 của một tệp lớn bằng cách đọc từng khối để tránh tràn RAM."""
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


def is_snr_already_extracted(output_dir: str, snr_key: str) -> Tuple[bool, int, str]:
    """
    Kiểm tra xem dữ liệu của tập SNR đã được giải nén sẵn sàng trên đĩa chưa.
    Trả về: (đã_sẵn_sàng, số_lượng_file_wav, đường_dẫn_thư_mục)
    """
    possible_paths = [
        os.path.join(output_dir, snr_key, "pump"),
        os.path.join(output_dir, "pump", snr_key),
        os.path.join(output_dir, snr_key),
    ]
    for p in possible_paths:
        if os.path.isdir(p):
            expected_ids = ["id_00", "id_02", "id_04", "id_06"]
            found_ids = [m for m in expected_ids if os.path.isdir(os.path.join(p, m))]
            if len(found_ids) >= 2:
                wav_count = 0
                for root, _, files in os.walk(p):
                    wav_count += sum(1 for f in files if f.lower().endswith(".wav"))
                # Một tập SNR của pump có > 4000 file wav. Nếu có trên 500 file thì coi như đã trích xuất
                if wav_count >= 500:
                    return True, wav_count, p
    return False, 0, ""


def download_file_with_resume(
    url_list: List[str],
    destination_path: str,
    expected_size: Optional[int] = None,
    expected_md5: Optional[str] = None,
    chunk_size: int = 2 * 1024 * 1024,
    timeout: int = 60,
    max_retries: int = 5,
    logger=None,
    checkpoint: Optional[DownloadCheckpoint] = None,
    snr_key: str = "",
) -> bool:
    """
    Tải file từ danh sách URL với tính năng HTTP Range Resume.
    Tự động tiếp tục từ vị trí đã tải nếu bị kill hoặc ngắt mạng.
    """
    global CURRENT_FILE_HANDLE
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
                logger.info(f"File {filename} đã tồn tại trọn vẹn ({format_size(current_size)}).")
            if expected_md5:
                actual_md5 = compute_md5(destination_path, logger=logger)
                if actual_md5.lower() == expected_md5.lower():
                    if logger:
                        logger.info(f"Xác thực MD5 khớp chính xác! Bỏ qua bước tải.")
                    if checkpoint:
                        checkpoint.save(snr_key, "downloaded", {"bytes": current_size})
                    return True
                else:
                    if logger:
                        logger.warning(
                            f"MD5 không khớp! Dự kiến: {expected_md5}, thực tế: {actual_md5}. Tải lại file."
                        )
                    os.remove(destination_path)
            else:
                return True

    # Thử lần lượt các URL mirror
    for url_idx, url in enumerate(url_list):
        if logger:
            logger.info(f"Đang kết nối nguồn {url_idx + 1}/{len(url_list)}: {url}")

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
                    pct = (existing_bytes / expected_size * 100) if expected_size else 0
                    if logger:
                        logger.info(
                            f"⚡ [RESUME] Phát hiện dữ liệu dở dang trước đó: {format_size(existing_bytes)} ({pct:.1f}%). "
                            f"Đang tiếp tục tải từ byte {existing_bytes}..."
                        )

                session = requests.Session()
                response = session.get(url, headers=headers, stream=True, timeout=timeout)

                # 206: Hỗ trợ Resume tiếp tục nối file
                if response.status_code == 206:
                    write_mode = "ab"
                    downloaded_so_far = existing_bytes
                    total_file_size = expected_size or (
                        int(response.headers.get("Content-Length", 0)) + existing_bytes
                    )
                # 200: Server gửi toàn bộ file
                elif response.status_code == 200:
                    write_mode = "wb"
                    downloaded_so_far = 0
                    total_file_size = int(response.headers.get("Content-Length", expected_size or 0))
                    if existing_bytes > 0 and logger:
                        logger.warning("Server không hỗ trợ Range 206, đang tải lại file từ đầu...")
                # 416: File tạm đã tải đủ 100%
                elif response.status_code == 416:
                    if logger:
                        logger.info("Server báo Range Not Satisfiable (file tạm đã hoàn thành 100%).")
                    if os.path.exists(temp_file):
                        shutil.move(temp_file, destination_path)
                        return True
                    break
                elif response.status_code in [403, 429]:
                    if logger:
                        logger.warning(f"Zenodo trả về mã lỗi {response.status_code}. Thử nguồn khác...")
                    break
                else:
                    response.raise_for_status()

                is_tty = sys.stdout.isatty()
                start_time = time.time()
                last_log_time = start_time
                last_flush_time = start_time
                bytes_since_last_log = 0

                if logger:
                    logger.info(
                        f"Bắt đầu tải {filename} (Tổng: {format_size(total_file_size)}, "
                        f"cần tải tiếp: {format_size(total_file_size - downloaded_so_far)})..."
                    )

                with open(temp_file, write_mode) as f:
                    CURRENT_FILE_HANDLE = f
                    for chunk in response.iter_content(chunk_size=chunk_size):
                        if not chunk:
                            continue
                        f.write(chunk)
                        chunk_len = len(chunk)
                        downloaded_so_far += chunk_len
                        bytes_since_last_log += chunk_len

                        now = time.time()

                        # Ép flush và fsync mỗi 5 giây hoặc mỗi khi tải thêm 16MB
                        # Đảm bảo nếu bị kill bất thình lình (kill -9) dữ liệu vẫn lưu trọn vẹn trên đĩa
                        if now - last_flush_time >= 5.0 or bytes_since_last_log >= 16 * 1024 * 1024:
                            f.flush()
                            try:
                                os.fsync(f.fileno())
                            except Exception:
                                pass
                            last_flush_time = now
                            if checkpoint:
                                checkpoint.save(snr_key, "downloading", {
                                    "downloaded_bytes": downloaded_so_far,
                                    "total_bytes": total_file_size,
                                })

                        # Ghi log tiến trình
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

                    CURRENT_FILE_HANDLE = None

                if is_tty:
                    print()

                # Đổi tên file tạm thành file chính thức sau khi tải hoàn tất
                if os.path.exists(temp_file):
                    shutil.move(temp_file, destination_path)
                    if logger:
                        logger.info(f"Đã tải xong tệp: {filename} ({format_size(os.path.getsize(destination_path))})")

                # Kiểm tra mã MD5
                if expected_md5:
                    actual_md5 = compute_md5(destination_path, logger=logger)
                    if actual_md5.lower() == expected_md5.lower():
                        if logger:
                            logger.info(f"Xác thực MD5 thành công cho {filename}!")
                        if checkpoint:
                            checkpoint.save(snr_key, "downloaded", {"bytes": total_file_size})
                        return True
                    else:
                        if logger:
                            logger.error(
                                f"LỖI: MD5 không khớp! Dự kiến: {expected_md5}, nhận được: {actual_md5}. Xóa tải lại..."
                            )
                        if os.path.exists(destination_path):
                            os.remove(destination_path)
                        retry_count += 1
                        continue

                if checkpoint:
                    checkpoint.save(snr_key, "downloaded", {"bytes": total_file_size})
                return True

            except (requests.RequestException, IOError) as e:
                retry_count += 1
                if logger:
                    logger.warning(f"Lỗi mạng ({e}). Thử lại lần {retry_count}/{max_retries} sau 5 giây...")
                time.sleep(5)

    if logger:
        logger.error(f"Không thể tải hoàn tất tệp: {filename}")
    return False


def extract_zip_file_with_resume(
    zip_path: str,
    extract_to: str,
    delete_zip: bool = False,
    logger=None,
    checkpoint: Optional[DownloadCheckpoint] = None,
    snr_key: str = "",
) -> bool:
    """
    Giải nén file zip với cơ chế resume:
    Bỏ qua các file .wav đã được giải nén từ trước nếu bị kill giữa chừng.
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
            members = zf.infolist()
            total_members = len(members)
            if logger:
                logger.info(f"Tổng số tệp âm thanh trong lưu trữ: {total_members}")

            last_log_time = time.time()
            skipped_count = 0
            extracted_count = 0

            for idx, member_info in enumerate(members):
                target_path = os.path.join(extract_to, member_info.filename)

                # Kiểm tra nếu file đã được giải nén hoàn chỉnh từ phiên chạy trước
                if os.path.exists(target_path):
                    if member_info.is_dir() or os.path.getsize(target_path) == member_info.file_size:
                        skipped_count += 1
                        continue

                zf.extract(member_info, path=extract_to)
                extracted_count += 1

                now = time.time()
                if logger and (now - last_log_time > 15):
                    pct = (idx + 1) / total_members * 100
                    logger.info(
                        f"  [Giải nén {filename}] Tiến độ: {idx + 1}/{total_members} files ({pct:.1f}%) "
                        f"[Mới: {extracted_count}, Đã có sẵn: {skipped_count}]"
                    )
                    last_log_time = now

        if logger:
            logger.info(
                f"Giải nén thành công {filename}! (Giải nén mới: {extracted_count}, Bỏ qua file cũ: {skipped_count})"
            )

        if checkpoint:
            checkpoint.save(snr_key, "completed", {"total_files": total_members})

        if delete_zip:
            if logger:
                logger.info(f"Đang xóa file zip {filename} để giải phóng dung lượng ổ đĩa...")
            os.remove(zip_path)

        return True
    except Exception as e:
        if logger:
            logger.error(f"Lỗi trong quá trình giải nén {filename}: {e}")
        return False


def get_default_data_dir() -> str:
    """
    Trả về đường dẫn lưu dữ liệu mặc định:
    1. Ưu tiên biến môi trường PUMP_DATA_DIR nếu được thiết lập.
    2. Nếu đang chạy trên Server (có thư mục /hdd3 hoặc /hdd3/users/dunglt),
       mặc định là: /hdd3/users/dunglt/edge_pump_asd/data
    3. Ngược lại (chạy ở local), mặc định là: ./data
    """
    env_dir = os.environ.get("PUMP_DATA_DIR")
    if env_dir:
        return env_dir
    server_dir = "/hdd3/users/dunglt/edge_pump_asd/data"
    if os.path.exists("/hdd3/users/dunglt") or os.path.exists("/hdd3"):
        return server_dir
    return "./data"


def download_mimii_pump(
    output_dir: str = "",
    snr_filter: str = "all",
    extract: bool = False,
    delete_zip: bool = False,
    skip_checksum: bool = False,
    force: bool = False,
    logger=None,
) -> bool:
    """
    Hàm tổng điều phối việc tải và chuẩn bị dữ liệu máy bơm từ MIMII Dataset.
    Tự động khôi phục và tiếp tục (Resume) khi bị ngắt.
    """
    global CURRENT_LOGGER
    if not output_dir:
        output_dir = get_default_data_dir()

    if logger is None:
        logger = setup_logger("MIMII_Pump_Downloader")
    CURRENT_LOGGER = logger
    register_signal_handler()

    os.makedirs(output_dir, exist_ok=True)
    checkpoint = DownloadCheckpoint(output_dir)

    keys_to_download = []
    if snr_filter.lower() == "all":
        keys_to_download = list(MIMII_PUMP_METADATA.keys())
    elif snr_filter in MIMII_PUMP_METADATA:
        keys_to_download = [snr_filter]
    else:
        logger.error(f"Mức SNR không hợp lệ: '{snr_filter}'. Chọn một trong: all, -6_dB, 0_dB, 6_dB.")
        return False

    logger.info("=" * 75)
    logger.info("   BẮT ĐẦU QUÁ TRÌNH TẢI DỮ LIỆU MÁY BƠM (MIMII PUMP DATASET)")
    logger.info(f"   Thư mục lưu trữ  : {os.path.abspath(output_dir)}")
    logger.info(f"   Các mức SNR chọn : {', '.join(keys_to_download)}")
    logger.info(f"   Tự động giải nén : {'BẬT' if extract else 'TẮT'}")
    logger.info(f"   Chế độ khôi phục : TỰ ĐỘNG RESUME (Chống mất dữ liệu khi bị kill)")
    logger.info(f"   Bắt buộc tải lại : {'BẬT' if force else 'TẮT'}")
    logger.info("=" * 75)

    success_all = True
    for snr_key in keys_to_download:
        meta = MIMII_PUMP_METADATA[snr_key]
        dest_file = os.path.join(output_dir, meta["filename"])

        logger.info(f"\n---------------------------------------------------------------------------")
        logger.info(f"KIỂM TRA TẬP: {meta['filename']} ({snr_key}) - Dung lượng gốc: {format_size(meta['size_bytes'])}")
        logger.info(f"---------------------------------------------------------------------------")

        # 1. Kiểm tra xem tập SNR này đã được giải nén sẵn sàng chưa (nếu không bật --force)
        if not force and extract:
            already_ready, wav_count, extracted_dir = is_snr_already_extracted(output_dir, snr_key)
            if already_ready:
                logger.info(
                    f"⚡ [BỎ QUA - ĐÃ HOÀN TẤT] Phát hiện tập {snr_key} đã có đầy đủ {wav_count} file .wav "
                    f"tại: {extracted_dir}."
                )
                logger.info(f"-> Không cần đào lại tập này, chuyển sang tập tiếp theo!")
                checkpoint.save(snr_key, "completed", {"wav_count": wav_count})
                continue

        # 2. Tải file zip (tự động resume từ file .part nếu đang dở dang)
        expected_md5 = None if skip_checksum else meta["md5"]
        download_ok = download_file_with_resume(
            url_list=meta["urls"],
            destination_path=dest_file,
            expected_size=meta["size_bytes"],
            expected_md5=expected_md5,
            logger=logger,
            checkpoint=checkpoint,
            snr_key=snr_key,
        )

        if not download_ok:
            logger.error(f"Thất bại khi tải {meta['filename']}!")
            success_all = False
            continue

        # 3. Giải nén (bỏ qua các file .wav đã được giải nén nếu trước đó bị kill giữa chừng)
        if extract:
            logger.info(f">>> Bắt đầu giải nén {meta['filename']}...")
            extract_dest = output_dir
            extract_ok = extract_zip_file_with_resume(
                zip_path=dest_file,
                extract_to=extract_dest,
                delete_zip=delete_zip,
                logger=logger,
                checkpoint=checkpoint,
                snr_key=snr_key,
            )
            if not extract_ok:
                logger.error(f"Thất bại khi giải nén {meta['filename']}!")
                success_all = False

    logger.info("\n" + "=" * 75)
    if success_all:
        logger.info(" HOÀN TẤT: Toàn bộ dữ liệu máy bơm đã được chuẩn bị thành công!")
    else:
        logger.warning(" KẾT THÚC CÓ CẢNH BÁO: Một số tệp tải hoặc giải nén gặp sự cố.")
    logger.info("=" * 75)

    return success_all


def parse_args():
    default_data_dir = get_default_data_dir()
    parser = argparse.ArgumentParser(
        description="Tải và quản lý tập dữ liệu âm thanh máy bơm (Pump) từ MIMII Dataset (Zenodo 3384388)."
    )
    parser.add_argument(
        "--output_dir",
        type=str,
        default=default_data_dir,
        help=f"Đường dẫn thư mục lưu trữ dữ liệu tải về (Mặc định: {default_data_dir})",
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
        "--force",
        action="store_true",
        help="Bắt buộc tải lại từ đầu, bỏ qua dữ liệu cũ.",
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
        force=args.force,
        logger=logger,
    )


if __name__ == "__main__":
    main()
