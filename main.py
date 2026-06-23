# 必要なライブラリのインポート
import pyautogui as pag
import os, os.path as osp
import datetime, time
from PIL import Image, ImageGrab
import img2pdf
import easyocr
import io
from fpdf import FPDF
from tkinter import messagebox, simpledialog, filedialog
import tkinter as tk
import cv2
import numpy as np
from ctypes import *
from ctypes.wintypes import *

_ocr_reader = None

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

def capture_and_save_pages(bbox, title):
    """
    ページをキャプチャして保存
    Args:
        bbox: キャプチャ範囲 (left, top, right, bottom)
        title: 保存時のタイトル
    Returns:
        page - 1: 保存したページ数
    """
    left, top, right, bottom = bbox
    h, w = bottom - top, right - left
    old = np.zeros((h, w, 3), np.uint8)
    page = 1
    prev_saved = None

    # 保存先フォルダの設定
    cd = os.getcwd()
    os.mkdir(osp.join(base_save_folder, title))
    os.chdir(osp.join(base_save_folder, title))

    while True:
        # ファイル名設定と時間計測開始
        filename = f"{page:03d}.png"
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
        cv2.imwrite(filename, ss)
        prev_saved = ss
        old = ss
        print(f'Page: {page}, {ss.shape}, {time.perf_counter() - start:.2f} sec')
        page += 1
        pag.press(page_change_key)

def _get_ocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        print("EasyOCRモデルを初期化しています（初回は時間がかかります）...")
        _ocr_reader = easyocr.Reader(['ja', 'en'])
    return _ocr_reader

def _find_japanese_font():
    candidates = [
        r"C:\Windows\Fonts\YuGothM.ttf",
        r"C:\Windows\Fonts\YuGothR.ttf",
        r"C:\Windows\Fonts\meiryo.ttc",
        r"C:\Windows\Fonts\meiryob.ttc",
        r"C:\Windows\Fonts\msgothic.ttc",
    ]
    return next((f for f in candidates if osp.exists(f)), None)

def _build_text_pdf(png_files, ocr_results, font_path, page_dims):
    """各ページのOCRテキストを不可視テキスト層として持つPDFを生成"""
    pdf = FPDF(unit='pt')
    pdf.set_auto_page_break(False)
    pdf.add_font('jpfont', fname=font_path)

    for png_path, page_ocr, (pw_pt, ph_pt) in zip(png_files, ocr_results, page_dims):
        pdf.add_page(format=(pw_pt, ph_pt))
        img = Image.open(png_path)
        img_w, img_h = img.size
        sx = pw_pt / img_w
        sy = ph_pt / img_h

        for (bbox, text, conf) in page_ocr:
            x_pt = float(bbox[0][0]) * sx
            y_pt = float(bbox[0][1]) * sy
            h_pt = (float(bbox[2][1]) - float(bbox[0][1])) * sy
            font_size = max(6.0, h_pt)

            pdf.set_font('jpfont', size=font_size)
            pdf.set_text_rendering_mode(3)  # 不可視
            pdf.set_xy(x_pt, y_pt)
            pdf.cell(text=text)

    return bytes(pdf.output())

def _merge_text_layer(pdf_path, text_pdf_bytes):
    """テキスト層PDFをimgPDFに重ね合わせる"""
    import pikepdf
    with pikepdf.open(pdf_path, allow_overwriting_input=True) as img_pdf:
        with pikepdf.open(io.BytesIO(text_pdf_bytes)) as txt_pdf:
            for img_page, txt_page in zip(img_pdf.pages, txt_pdf.pages):
                txt_contents = txt_page.get("/Contents")
                if txt_contents is None:
                    continue

                if isinstance(txt_contents, pikepdf.Array):
                    appended = [img_pdf.make_indirect(img_pdf.copy_foreign(s))
                                for s in txt_contents]
                else:
                    appended = [img_pdf.make_indirect(img_pdf.copy_foreign(txt_contents))]

                img_contents = img_page.get("/Contents")
                if img_contents is None:
                    img_page["/Contents"] = (appended[0] if len(appended) == 1
                                             else pikepdf.Array(appended))
                else:
                    if not isinstance(img_contents, pikepdf.Array):
                        img_page["/Contents"] = pikepdf.Array([img_contents])
                    for s in appended:
                        img_page["/Contents"].append(s)

                txt_res = txt_page.get("/Resources")
                if txt_res is None or "/Font" not in txt_res:
                    continue
                if "/Resources" not in img_page:
                    img_page["/Resources"] = pikepdf.Dictionary()
                if "/Font" not in img_page["/Resources"]:
                    img_page["/Resources"]["/Font"] = pikepdf.Dictionary()
                for k, v in txt_res["/Font"].items():
                    img_page["/Resources"]["/Font"][k] = img_pdf.copy_foreign(v)

        img_pdf.save(pdf_path)

def apply_ocr(pdf_path, png_files):
    """EasyOCRでテキストを認識→ログ出力→PDFにテキスト層を埋め込む"""
    reader = _get_ocr_reader()
    all_results = []

    for i, png_path in enumerate(png_files, start=1):
        print(f"\n--- Page {i} ({osp.basename(png_path)}) ---")
        img_arr = np.array(Image.open(png_path).convert('RGB'))
        detections = reader.readtext(img_arr)
        page_results = []
        for (bbox, text, conf) in detections:
            print(f"  [{conf:.2f}] {text}")
            page_results.append((bbox, text, conf))
        all_results.append(page_results)

    font_path = _find_japanese_font()
    if font_path is None:
        print("警告: 日本語フォントが見つかりません。テキスト層の埋め込みをスキップします。")
        return

    import pikepdf
    page_dims = []
    with pikepdf.open(pdf_path) as pdf:
        for page in pdf.pages:
            mb = page.mediabox
            page_dims.append((float(mb[2]), float(mb[3])))

    text_pdf_bytes = _build_text_pdf(png_files, all_results, font_path, page_dims)
    _merge_text_layer(pdf_path, text_pdf_bytes)
    print(f"\nテキスト層を埋め込みました: {pdf_path}")


def ask_pdf_split_mode(root):
    """単一 or 分割を選択させる。(mode, chunk_size, use_ocr) を返す。キャンセル時は (None, None, None)"""
    dialog = tk.Toplevel(root)
    dialog.title("書き出しモード選択")
    dialog.resizable(False, False)

    tk.Label(dialog, text="書き出し方法を選択してください", padx=20, pady=12).pack()

    mode_var = tk.StringVar(value='single')
    chunk_var = tk.DoubleVar(value=50.0)
    ocr_var = tk.BooleanVar(value=False)
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
    tk.Checkbutton(ocr_frame, text="OCRテキストを埋め込む（初回はモデルDLあり・処理に時間がかかります）",
                   variable=ocr_var).pack(anchor='w')

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
        return None, None, None
    return mode, chunk_var.get(), ocr_var.get()


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

    mode, chunk_size, use_ocr = ask_pdf_split_mode(root)
    if mode is None:
        root.destroy()
        return

    base_name = osp.basename(png_folder)

    def write_pdf(png_list, path):
        with open(path, 'wb') as f:
            f.write(img2pdf.convert(png_list))
        if use_ocr:
            try:
                apply_ocr(path, png_list)
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
                out_path = osp.join(out_folder, f"{base_name}_{idx:03d}.pdf")
                write_pdf(chunk, out_path)
        except RuntimeError as e:
            messagebox.showerror("エラー", str(e))
            root.destroy()
            return
        messagebox.showinfo(
            "完了",
            f"{len(png_files)} ページを {total} 個のPDFに分割して保存しました。\n{out_folder}",
        )

    root.destroy()


def ask_mode():
    """起動時にモードを選択させる。(mode, page_key) を返す。mode は 'capture'/'pdf'/'cancel'"""
    root = tk.Tk()
    root.withdraw()

    dialog = tk.Toplevel(root)
    dialog.title("モード選択")
    dialog.resizable(False, False)

    tk.Label(dialog, text="実行するモードを選択してください", padx=20, pady=12).pack()

    result = tk.StringVar(value='cancel')
    key_var = tk.StringVar(value='right')

    key_frame = tk.LabelFrame(dialog, text="ページめくりキー（Kindleキャプチャ時）", padx=12, pady=6)
    key_frame.pack(padx=20, pady=(0, 8), fill='x')
    tk.Radiobutton(key_frame, text="→ 右キー（次ページ）", variable=key_var, value='right').pack(side='left', padx=8)
    tk.Radiobutton(key_frame, text="← 左キー（次ページ）", variable=key_var, value='left').pack(side='left', padx=8)

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

    return result.get(), key_var.get()


def main():
    """メイン処理"""
    global base_save_folder

    mode, page_key = ask_mode()
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
    total_pages = capture_and_save_pages(bbox, title)

    # 完了メッセージを表示
    messagebox.showinfo("完了",
                       f"スクリーンショットの撮影が終了しました。\n"
                       f"合計 {total_pages} ページを保存しました。")

if __name__ == "__main__":
    main()
