# 必要なライブラリのインポート
import pyautogui as pag
import os, os.path as osp
import datetime, time
from PIL import Image, ImageGrab
import img2pdf
from tkinter import messagebox, simpledialog, filedialog
import tkinter as tk
import cv2
import numpy as np
from ctypes import *
from ctypes.wintypes import *

_paddle_reader = None
_easy_reader = None
_easy_reader_gpu = None
_rapid_reader = None

# グローバル変数の設定
pag.FAILSAFE = False               # フェイルセーフを無効化
kindle_window_title = 'Kindle for PC'  # Kindle for PCのウィンドウタイトル
page_change_key = 'right'       # 次のページへ移動するキー
kindle_fullscreen_wait = 5     # フルスクリーン後の待機時間(秒)
l_margin = 1                   # 左側マージン
r_margin = 1                   # 右側マージン
waitsec = 0.30                 # キー押下後の待機時間(秒)

def find_kindle_window():
    """
    Kindleウィンドウを検索してハンドルを返す関数
    Returns:
        ghwnd: Kindleウィンドウのハンドル。見つからない場合はNone
    """
    # Windows APIの関数を取得
    EnumWindows = windll.user32.EnumWindows
    GetWindowText = windll.user32.GetWindowTextW
    GetWindowTextLength = windll.user32.GetWindowTextLengthW
    WNDENUMPROC = WINFUNCTYPE(c_bool, POINTER(c_int), POINTER(c_int))
    ghwnd = None

    def EnumWindowsProc(hwnd, lParam):
        """ウィンドウ列挙のためのコールバック関数"""
        nonlocal ghwnd
        length = GetWindowTextLength(hwnd)
        buff = create_unicode_buffer(length + 1)
        GetWindowText(hwnd, buff, length + 1)
        if kindle_window_title in buff.value:
            ghwnd = hwnd
            return False
        return True

    EnumWindows(WNDENUMPROC(EnumWindowsProc), 0)
    return ghwnd

def setup_kindle_window(hwnd):
    """
    Kindleウィンドウを前面に表示しフォーカスを設定
    Args:
        hwnd: ウィンドウハンドル
    """
    SetForegroundWindow = windll.user32.SetForegroundWindow
    GetWindowRect = windll.user32.GetWindowRect

    # SetForegroundWindow制限を回避するためAltキーイベントを送出
    windll.user32.keybd_event(0x12, 0, 0, 0)        # Alt キー押下
    windll.user32.keybd_event(0x12, 0, 0x0002, 0)   # Alt キー解放

    # ウィンドウを前面に表示
    SetForegroundWindow(hwnd)

    rect = RECT()
    GetWindowRect(hwnd, pointer(rect))

    # クリックしてフォーカスを設定
    sc_w, sc_h = pag.size()
    x = max(1, min(rect.left + 60, sc_w - 2))
    y = max(1, min(rect.top + 10, sc_h - 2))
    pag.moveTo(x, y)
    pag.click()
    time.sleep(1)

def get_screen_size():
    """画面サイズを取得"""
    return pag.size()

def get_title():
    """
    保存用のタイトルを取得
    空の場合は現在時刻を使用
    """
    default_title = str(datetime.datetime.now().strftime("%Y%m%d%H%M%S"))
    tt = simpledialog.askstring('タイトルを入力','タイトルを入力して下さい(空白の場合現在の時刻)')
    return tt if tt != '' else default_title

def get_save_folder():
    """保存先フォルダを選択"""
    return filedialog.askdirectory(title='保存するフォルダを選択してください')

def capture_and_save_pages(bbox, title, img_format='png'):
    """
    ページをキャプチャして保存
    Args:
        bbox: キャプチャ範囲 (left, top, right, bottom)
        title: 保存時のタイトル
        img_format: 保存する画像形式 ('png' または 'jpg')
    Returns:
        page - 1: 保存したページ数
    """
    left, top, right, bottom = bbox
    h, w = bottom - top, right - left
    old = np.zeros((h, w, 3), np.uint8)
    page = 1
    prev_saved = None

    # 保存形式に応じた拡張子とcv2.imwriteのパラメータ
    ext = 'jpg' if img_format == 'jpg' else 'png'
    write_params = [cv2.IMWRITE_JPEG_QUALITY, 95] if ext == 'jpg' else []

    # 保存先フォルダの設定
    cd = os.getcwd()
    os.mkdir(osp.join(base_save_folder, title))
    os.chdir(osp.join(base_save_folder, title))

    while True:
        # ファイル名設定と時間計測開始
        filename = f"{page:03d}.{ext}"
        start = time.perf_counter()

        while True:
            # ページめくり後の待機
            time.sleep(waitsec)

            # Kindleウィンドウ領域のみキャプチャ
            s = ImageGrab.grab(bbox=bbox)
            ss = cv2.cvtColor(np.array(s), cv2.COLOR_RGB2BGR)

            # ページめくり完了を確認
            if not np.array_equal(old, ss):
                break

            # タイムアウト処理
            if time.perf_counter() - start > 5.0:
                os.chdir(cd)
                return page - 1

        # 前回保存と同じ内容なら最終ページ（終了）
        if prev_saved is not None and np.array_equal(prev_saved, ss):
            os.chdir(cd)
            return page - 1

        # 画像保存と次ページへ
        cv2.imwrite(filename, ss, write_params)
        prev_saved = ss
        old = ss
        print(f'Page: {page}, {ss.shape}, {time.perf_counter() - start:.2f} sec')
        page += 1
        pag.press(page_change_key)

def _get_paddle_reader():
    global _paddle_reader
    if _paddle_reader is None:
        print("PaddleOCRモデルを初期化しています（初回は時間がかかります）...")
        import warnings, sys, os
        from paddleocr import PaddleOCR
        os.environ.setdefault('GLOG_minloglevel', '3')
        os.environ.setdefault('FLAGS_logtostderr', '0')
        os.environ.setdefault('PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK', 'True')
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            devnull = open(os.devnull, 'w')
            old_stdout, old_stderr = sys.stdout, sys.stderr
            sys.stdout = sys.stderr = devnull
            try:
                _paddle_reader = PaddleOCR(lang='japan', device='cpu', ocr_version='PP-OCRv4')
            finally:
                sys.stdout, sys.stderr = old_stdout, old_stderr
                devnull.close()
    return _paddle_reader

def _get_easy_reader(gpu=False):
    global _easy_reader, _easy_reader_gpu
    if _easy_reader is None or _easy_reader_gpu != gpu:
        print(f"EasyOCRモデルを初期化しています（{'GPU' if gpu else 'CPU'}）...")
        import easyocr
        _easy_reader = easyocr.Reader(['ja', 'en'], gpu=gpu)
        _easy_reader_gpu = gpu
    return _easy_reader

def _get_rapid_reader():
    global _rapid_reader
    if _rapid_reader is None:
        print("RapidOCRモデルを初期化しています（DirectML GPU）...")
        from rapidocr import RapidOCR, LangRec
        _rapid_reader = RapidOCR(params={
            'EngineConfig.onnxruntime.use_dml': True,
            'Rec.lang_type': LangRec.JAPAN,
            'Global.log_level': 'warning',
        })
    return _rapid_reader

def _make_tounicode_cmap():
    """UTF-16BEのIdentity-H用ToUnicode CMap（BMP全域）"""
    return (
        b"/CIDInit /ProcSet findresource begin\n"
        b"12 dict begin\n"
        b"begincmap\n"
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS2) /Supplement 0 >> def\n"
        b"/CMapName /Adobe-Identity-UCS2 def\n"
        b"/CMapType 2 def\n"
        b"1 begincodespacerange\n"
        b"<0000> <FFFF>\n"
        b"endcodespacerange\n"
        b"2 beginbfrange\n"
        b"<0020> <D7FF> <0020>\n"
        b"<E000> <FFFF> <E000>\n"
        b"endbfrange\n"
        b"endcmap\n"
        b"CMapToUnicode end"
    )

def _embed_text_layer(pdf_path, png_files, ocr_results):
    """pikepdfで不可視テキスト層をPDFに直接書き込む"""
    import pikepdf, tempfile, os

    tmp_path = pdf_path + '.tmp.pdf'
    try:
        with pikepdf.open(pdf_path) as pdf:
            tounicode_ref = pdf.make_indirect(pikepdf.Stream(pdf, _make_tounicode_cmap()))

            cid_font = pdf.make_indirect(pikepdf.Dictionary(
                Type=pikepdf.Name("/Font"),
                Subtype=pikepdf.Name("/CIDFontType2"),
                BaseFont=pikepdf.Name("/Arial-Unicode"),
                CIDSystemInfo=pikepdf.Dictionary(
                    Registry=pikepdf.String("Adobe"),
                    Ordering=pikepdf.String("UCS2"),
                    Supplement=0,
                ),
                DW=1000,
            ))
            type0_font = pdf.make_indirect(pikepdf.Dictionary(
                Type=pikepdf.Name("/Font"),
                Subtype=pikepdf.Name("/Type0"),
                BaseFont=pikepdf.Name("/Arial-Unicode"),
                Encoding=pikepdf.Name("/Identity-H"),
                DescendantFonts=pikepdf.Array([cid_font]),
                ToUnicode=tounicode_ref,
            ))

            total = len(pdf.pages)
            for page_idx, (page, png_path, page_ocr) in enumerate(zip(pdf.pages, png_files, ocr_results), start=1):
                print(f"  埋め込み中: Page {page_idx}/{total}", flush=True)
                if not page_ocr:
                    continue

                img = Image.open(png_path)
                img_w, img_h = img.size
                mb = page.mediabox
                pw = float(mb[2])
                ph = float(mb[3])
                sx = pw / img_w
                sy = ph / img_h

                lines = [b"q", b"BT", b"3 Tr"]
                for (bbox, text, conf) in page_ocr:
                    x = float(bbox[0][0]) * sx
                    y = ph - float(bbox[2][1]) * sy
                    h = (float(bbox[2][1]) - float(bbox[0][1])) * sy
                    fs = max(8.0, h)
                    hex_str = text.encode('utf-16-be').hex().upper()
                    lines.append(f"/F1 {fs:.1f} Tf".encode())
                    lines.append(f"1 0 0 1 {x:.1f} {y:.1f} Tm".encode())
                    lines.append(f"<{hex_str}> Tj".encode())
                lines.extend([b"ET", b"Q"])

                new_stream = pdf.make_indirect(pikepdf.Stream(pdf, b"\n".join(lines)))

                existing = page.get("/Contents")
                if existing is None:
                    page["/Contents"] = new_stream
                elif isinstance(existing, pikepdf.Array):
                    existing.append(new_stream)
                else:
                    page["/Contents"] = pikepdf.Array([existing, new_stream])

                if "/Resources" not in page:
                    page["/Resources"] = pikepdf.Dictionary()
                if "/Font" not in page["/Resources"]:
                    page["/Resources"]["/Font"] = pikepdf.Dictionary()
                page["/Resources"]["/Font"]["/F1"] = type0_font

            print("  保存中...", flush=True)
            pdf.save(tmp_path)

        os.replace(tmp_path, pdf_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise

def apply_ocr(pdf_path, png_files, engine='paddle', gpu=False):
    """OCRでテキストを認識→ログ出力→PDFにテキスト層を埋め込む"""
    if engine == 'paddle':
        reader = _get_paddle_reader()
    elif engine == 'rapid':
        reader = _get_rapid_reader()
    else:
        reader = _get_easy_reader(gpu=gpu)

    all_results = []
    for i, png_path in enumerate(png_files, start=1):
        print(f"\n--- Page {i} ({osp.basename(png_path)}) ---", flush=True)
        img_arr = np.array(Image.open(png_path).convert('RGB'))

        if engine == 'paddle':
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', DeprecationWarning)
                result = reader.ocr(img_arr)
            r = result[0] if result else {}
            page_results = [
                (poly.tolist(), text, conf)
                for poly, text, conf in zip(
                    r.get('rec_polys', []), r.get('rec_texts', []), r.get('rec_scores', [])
                )
            ]
        elif engine == 'rapid':
            result = reader(img_arr)
            page_results = []
            if result.boxes is not None:
                for bbox, text, conf in zip(result.boxes, result.txts, result.scores):
                    page_results.append((bbox.tolist(), text, conf))
        else:
            page_results = [
                (bbox, text, conf)
                for bbox, text, conf in reader.readtext(img_arr)
            ]

        for _, text, conf in page_results:
            print(f"  [{conf:.2f}] {text}")
        print(f"  → {len(page_results)} 件認識")
        all_results.append(page_results)

    print(f"\n全ページのOCR完了。テキスト層を埋め込み中...", flush=True)
    _embed_text_layer(pdf_path, png_files, all_results)
    print(f"テキスト層を埋め込みました: {pdf_path}")


def ask_pdf_split_mode(root):
    """単一 or 分割を選択させる。(mode, chunk_size, use_ocr, engine, use_gpu) を返す。キャンセル時は全て None"""
    dialog = tk.Toplevel(root)
    dialog.title("書き出しモード選択")
    dialog.resizable(False, False)

    tk.Label(dialog, text="書き出し方法を選択してください", padx=20, pady=12).pack()

    mode_var = tk.StringVar(value='split')
    chunk_var = tk.DoubleVar(value=25.0)
    ocr_var = tk.BooleanVar(value=False)
    engine_var = tk.StringVar(value='rapid')
    gpu_var = tk.BooleanVar(value=False)
    result = tk.StringVar(value='cancel')

    radio_frame = tk.Frame(dialog, padx=24)
    radio_frame.pack(anchor='w')

    tk.Radiobutton(radio_frame, text="単一PDFで書き出す",
                   variable=mode_var, value='single').grid(row=0, column=0, columnspan=3, sticky='w', pady=2)
    tk.Radiobutton(radio_frame, text="分割して書き出す（1PDFあたり上限",
                   variable=mode_var, value='split').grid(row=1, column=0, sticky='w', pady=2)

    spinbox = tk.Spinbox(radio_frame, from_=1, to=9999, increment=10,
                         textvariable=chunk_var, width=6, format="%.0f")
    spinbox.grid(row=1, column=1, sticky='w')
    tk.Label(radio_frame, text="MB）").grid(row=1, column=2, sticky='w')

    ocr_frame = tk.LabelFrame(dialog, text="OCR", padx=12, pady=6)
    ocr_frame.pack(padx=20, pady=(8, 0), fill='x')

    engine_frame = tk.Frame(ocr_frame)
    gpu_frame = tk.Frame(engine_frame)

    def on_engine_change(*_):
        if engine_var.get() == 'easy':
            gpu_frame.pack(anchor='w', padx=24, pady=(2, 0))
        else:
            gpu_frame.pack_forget()

    def on_ocr_toggle():
        if ocr_var.get():
            engine_frame.pack(anchor='w', padx=8, pady=(4, 0))
            on_engine_change()
        else:
            engine_frame.pack_forget()

    tk.Checkbutton(ocr_frame, text="OCRテキストを埋め込む（初回はモデルDLあり・処理に時間がかかります）",
                   variable=ocr_var, command=on_ocr_toggle).pack(anchor='w')

    tk.Radiobutton(engine_frame, text="RapidOCR（GPU・DirectML・推奨）",
                   variable=engine_var, value='rapid', command=on_engine_change).pack(anchor='w')
    tk.Radiobutton(engine_frame, text="PaddleOCR（高精度・CPU）",
                   variable=engine_var, value='paddle', command=on_engine_change).pack(anchor='w')
    tk.Radiobutton(engine_frame, text="EasyOCR（GPU・CUDA）",
                   variable=engine_var, value='easy', command=on_engine_change).pack(anchor='w')

    tk.Radiobutton(gpu_frame, text="CPU", variable=gpu_var, value=False).pack(side='left', padx=4)
    tk.Radiobutton(gpu_frame, text="GPU", variable=gpu_var, value=True).pack(side='left', padx=4)

    btn_frame = tk.Frame(dialog, padx=20, pady=10)
    btn_frame.pack()

    def ok():
        result.set(mode_var.get())
        dialog.destroy()

    def cancel():
        result.set('cancel')
        dialog.destroy()

    tk.Button(btn_frame, text="OK", width=10, command=ok).grid(row=0, column=0, padx=6)
    tk.Button(btn_frame, text="キャンセル", width=10, command=cancel).grid(row=0, column=1, padx=6)

    dialog.protocol("WM_DELETE_WINDOW", cancel)
    dialog.grab_set()
    root.wait_window(dialog)

    mode = result.get()
    if mode == 'cancel':
        return None, None, None, None, None
    return mode, chunk_var.get(), ocr_var.get(), engine_var.get(), gpu_var.get()


def convert_png_to_pdf():
    """既存フォルダのPNGをPDFに変換する（単一 or 分割）"""
    root = tk.Tk()
    root.withdraw()

    png_folder = filedialog.askdirectory(
        title='PNGが入ったフォルダを選択してください', parent=root)
    if not png_folder:
        root.destroy()
        return

    png_files = sorted([
        osp.join(png_folder, f)
        for f in os.listdir(png_folder)
        if f.lower().endswith(('.png', '.jpg', '.jpeg'))
    ])

    if not png_files:
        messagebox.showerror("エラー", "選択したフォルダにPNGファイルが見つかりません")
        root.destroy()
        return

    mode, chunk_size, use_ocr, ocr_engine, use_gpu = ask_pdf_split_mode(root)
    if mode is None:
        root.destroy()
        return

    base_name = osp.basename(png_folder)

    def write_pdf(png_list, path):
        print(f"PDF作成中: {osp.basename(path)} ({len(png_list)}ページ)...", flush=True)
        with open(path, 'wb') as f:
            f.write(img2pdf.convert(png_list))
        print(f"PDF作成完了: {osp.basename(path)}", flush=True)
        if use_ocr:
            try:
                apply_ocr(path, png_list, engine=ocr_engine, gpu=use_gpu)
            except Exception as e:
                raise RuntimeError(f"OCR処理に失敗しました。\n詳細: {e}")

    if mode == 'single':
        output_path = filedialog.asksaveasfilename(
            title='PDFの保存先を選択してください',
            defaultextension='.pdf',
            filetypes=[('PDF files', '*.pdf')],
            initialfile=base_name + '.pdf',
            parent=root,
        )
        if not output_path:
            root.destroy()
            return
        try:
            write_pdf(png_files, output_path)
        except RuntimeError as e:
            messagebox.showerror("エラー", str(e))
            root.destroy()
            return
        root.deiconify()
        root.lift()
        root.attributes('-topmost', True)
        messagebox.showinfo("完了", f"{len(png_files)} ページのPDFを保存しました。\n{output_path}")

    else:
        out_folder = filedialog.askdirectory(
            title='分割PDFの保存先フォルダを選択してください', parent=root)
        if not out_folder:
            root.destroy()
            return
        limit_bytes = chunk_size * 1024 * 1024
        chunks, current, current_size = [], [], 0
        for f in png_files:
            fsize = osp.getsize(f)
            if current and current_size + fsize > limit_bytes:
                chunks.append(current)
                current, current_size = [f], fsize
            else:
                current.append(f)
                current_size += fsize
        if current:
            chunks.append(current)
        total = len(chunks)
        try:
            for idx, chunk in enumerate(chunks, start=1):
                print(f"\n=== チャンク {idx}/{total} ===", flush=True)
                out_path = osp.join(out_folder, f"{base_name}_{idx:03d}.pdf")
                write_pdf(chunk, out_path)
        except RuntimeError as e:
            messagebox.showerror("エラー", str(e))
            root.destroy()
            return
        root.deiconify()
        root.lift()
        root.attributes('-topmost', True)
        messagebox.showinfo(
            "完了",
            f"{len(png_files)} ページを {total} 個のPDFに分割して保存しました。\n{out_folder}",
        )

    root.destroy()


def ask_mode():
    """起動時にモードを選択させる。(mode, page_key, img_format) を返す。mode は 'capture'/'pdf'/'cancel'"""
    root = tk.Tk()
    root.withdraw()

    dialog = tk.Toplevel(root)
    dialog.title("モード選択")
    dialog.resizable(False, False)

    tk.Label(dialog, text="実行するモードを選択してください", padx=20, pady=12).pack()

    result = tk.StringVar(value='cancel')
    key_var = tk.StringVar(value='right')
    format_var = tk.StringVar(value='png')

    key_frame = tk.LabelFrame(dialog, text="ページめくりキー（Kindleキャプチャ時）", padx=12, pady=6)
    key_frame.pack(padx=20, pady=(0, 8), fill='x')
    tk.Radiobutton(key_frame, text="→ 右キー（次ページ）", variable=key_var, value='right').pack(side='left', padx=8)
    tk.Radiobutton(key_frame, text="← 左キー（次ページ）", variable=key_var, value='left').pack(side='left', padx=8)

    format_frame = tk.LabelFrame(dialog, text="保存する画像形式（Kindleキャプチャ時）", padx=12, pady=6)
    format_frame.pack(padx=20, pady=(0, 8), fill='x')
    tk.Radiobutton(format_frame, text="PNG（可逆・高画質）", variable=format_var, value='png').pack(side='left', padx=8)
    tk.Radiobutton(format_frame, text="JPG（軽量）", variable=format_var, value='jpg').pack(side='left', padx=8)

    btn_frame = tk.Frame(dialog, padx=20, pady=8)
    btn_frame.pack()

    def select(val):
        result.set(val)
        dialog.destroy()

    tk.Button(btn_frame, text="Kindleキャプチャ", width=16,
              command=lambda: select('capture')).grid(row=0, column=0, padx=6, pady=4)
    tk.Button(btn_frame, text="PNG → PDF 変換", width=16,
              command=lambda: select('pdf')).grid(row=0, column=1, padx=6, pady=4)
    tk.Button(btn_frame, text="何もしない", width=16,
              command=lambda: select('cancel')).grid(row=0, column=2, padx=6, pady=4)

    dialog.protocol("WM_DELETE_WINDOW", lambda: select('cancel'))
    dialog.grab_set()
    root.wait_window(dialog)
    root.destroy()

    return result.get(), key_var.get(), format_var.get()


def main():
    """メイン処理"""
    global base_save_folder

    mode, page_key, img_format = ask_mode()
    if mode == 'pdf':
        convert_png_to_pdf()
        return
    if mode == 'cancel':
        return

    global page_change_key
    page_change_key = page_key

    # Kindleウィンドウを探索
    hwnd = find_kindle_window()
    if hwnd is None:
        messagebox.showerror("エラー", "Kindleが見つかりません")
        return

    # ウィンドウの設定
    setup_kindle_window(hwnd)

    # 画面サイズを取得してマウス移動
    sc_w, sc_h = get_screen_size()
    pag.moveTo(sc_w - 200, sc_h - 1)
    time.sleep(kindle_fullscreen_wait)

    # タイトルと保存先の取得
    title = get_title()
    base_save_folder = get_save_folder()
    if not base_save_folder:
        messagebox.showerror("エラー", "保存先フォルダが選択されていません")
        return

    # ダイアログ後にKindleウィンドウを再フォーカス
    setup_kindle_window(hwnd)
    pag.moveTo(sc_w - 200, sc_h - 1)
    time.sleep(1)

    # Kindleウィンドウの矩形を取得してキャプチャ範囲を設定
    GetWindowRect = windll.user32.GetWindowRect
    rect = RECT()
    GetWindowRect(hwnd, pointer(rect))
    bbox = (rect.left, rect.top, rect.right, rect.bottom)

    # キャプチャを実行
    total_pages = capture_and_save_pages(bbox, title, img_format)

    # 完了メッセージを表示
    messagebox.showinfo("完了",
                       f"スクリーンショットの撮影が終了しました。\n"
                       f"合計 {total_pages} ページを保存しました。")

if __name__ == "__main__":
    main()
