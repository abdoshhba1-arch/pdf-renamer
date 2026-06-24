#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================================
 تطبيق إعادة تسمية ملفات PDF الدفعية + الترقيم الفوري التلقائي
 PDF Batch Renamer + Live Auto-Numbering
============================================================================
صُنع بواسطة عبدالله بن أخوك 🙂

يعمل هذا الملف مباشرة عبر:  python app.py
يعتمد فقط على مكتبة بايثون القياسية، باستثناء tkinterdnd2 (اختيارية)
لتفعيل خاصية السحب والإفلات من خارج البرنامج. في حال عدم توفرها، يعمل
البرنامج بكل وظائفه الأخرى بدون أي مشاكل.
============================================================================
"""

import os
import re
import sys
import shutil
import uuid
import threading
import time
from datetime import datetime

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

# ----------------------------------------------------------------------------
# محاولة استيراد tkinterdnd2 بشكل اختياري (Graceful Fallback)
# ----------------------------------------------------------------------------
DND_AVAILABLE = False
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except Exception:
    DND_AVAILABLE = False

ATTRIBUTION_TEXT = "🙂 صُنع بواسطة عبدالله بن أخوك 🙂"

INVALID_CHARS_PATTERN = re.compile(r'[\\/:*?"<>|]')


# ============================================================================
# دوال مساعدة عامة (Helpers)
# ============================================================================

def natural_sort_key(text):
    """
    مفتاح فرز طبيعي (Natural Sort) بحيث file2 تسبق file10.
    يقسّم النص إلى أجزاء رقمية وأجزاء نصية ويحوّل الأرقام لقيم صحيحة للمقارنة.
    """
    parts = re.split(r'(\d+)', text)
    key = []
    for part in parts:
        if part.isdigit():
            key.append((1, int(part)))
        else:
            key.append((0, part.lower()))
    return key


def sanitize_filename(name):
    """تنظيف الاسم من الرموز غير المسموحة في أسماء ملفات ويندوز."""
    cleaned = INVALID_CHARS_PATTERN.sub('_', name)
    cleaned = cleaned.strip().strip('.')
    if not cleaned:
        cleaned = "ملف"
    return cleaned


def build_name_from_pattern(pattern, n, add_date):
    """
    بناء اسم الملف النهائي (بدون الامتداد) بناءً على نمط التسمية المخصص.
    - يستبدل {n} بالرقم التسلسلي.
    - إن لم يحتوِ النمط على {n}، نضيف الرقم كنهاية احتياطية لتفادي تكرار الأسماء.
    - يضيف بادئة التاريخ إن طُلب ذلك.
    """
    pattern = pattern.strip() if pattern and pattern.strip() else "{n}"
    if "{n}" in pattern:
        base = pattern.replace("{n}", str(n))
    else:
        base = f"{pattern}_{n}"
    base = sanitize_filename(base)
    if add_date:
        date_prefix = datetime.now().strftime("%Y-%m-%d_")
        base = date_prefix + base
    return base


def list_pdf_files(folder):
    """إرجاع قائمة بأسماء ملفات PDF الموجودة في المجلد (بدون مسارات فرعية)."""
    try:
        entries = os.listdir(folder)
    except Exception:
        return []
    return [f for f in entries if f.lower().endswith(".pdf")
            and os.path.isfile(os.path.join(folder, f))]


def extract_existing_numbers(files):
    """
    استخراج الأرقام التسلسلية المستخدمة فعليًا من أسماء ملفات مثل 1.pdf / 12.pdf
    تُستخدم في تحديد "أول فجوة فاضية" للترقيم الفوري.
    """
    numbers = set()
    for f in files:
        name, ext = os.path.splitext(f)
        if ext.lower() == ".pdf" and name.isdigit():
            numbers.add(int(name))
    return numbers


def first_available_gap(used_numbers, start=1):
    """إيجاد أول رقم فاضٍ متاح أكبر من أو يساوي start وغير موجود في used_numbers."""
    n = start
    while n in used_numbers:
        n += 1
    return n


def is_file_size_stable(path, wait_seconds=0.5):
    """
    فحص استقرار حجم الملف للتأكد أنه لم يكن قيد نسخ/كتابة.
    يقارن الحجم مرتين بفارق زمني صغير.
    """
    try:
        size1 = os.path.getsize(path)
    except OSError:
        return False
    time.sleep(wait_seconds)
    try:
        size2 = os.path.getsize(path)
    except OSError:
        return False
    return size1 == size2


def safe_two_phase_move(src, dst):
    """
    تنفيذ عملية نقل/إعادة تسمية بخطوتين عبر اسم وسيط مؤقت فريد (UUID)
    لمنع أي تعارض في حال كانت الأسماء متشابكة (مثل تبديل أسماء ملفات ببعضها).
    """
    folder = os.path.dirname(dst) or "."
    temp_name = os.path.join(folder, f".__tmp_{uuid.uuid4().hex}.pdf")
    shutil.move(src, temp_name)
    shutil.move(temp_name, dst)


# ============================================================================
# نافذة المعاينة (Preview Window)
# ============================================================================

class PreviewWindow(tk.Toplevel):
    def __init__(self, parent, rename_plan, excluded_files, conflicts):
        super().__init__(parent)
        self.title("معاينة عملية إعادة التسمية")
        self.geometry("650x550")

        tk.Label(self, text="معاينة التغييرات المقترحة", font=("Arial", 13, "bold")).pack(pady=8)

        frame = tk.Frame(self)
        frame.pack(fill="both", expand=True, padx=10, pady=5)

        tree = ttk.Treeview(frame, columns=("old", "new"), show="headings", height=15)
        tree.heading("old", text="الاسم الحالي")
        tree.heading("new", text="الاسم الجديد")
        tree.column("old", width=280)
        tree.column("new", width=280)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        for old_name, new_name in rename_plan:
            tree.insert("", "end", values=(old_name, new_name))

        # الملفات المستبعدة
        tk.Label(self, text="الملفات المستبعدة (لن تتغيّر):", font=("Arial", 10, "bold")).pack(
            anchor="e", padx=10, pady=(10, 0))
        excluded_box = tk.Listbox(self, height=5)
        excluded_box.pack(fill="x", padx=10, pady=(0, 5))
        for f in excluded_files:
            excluded_box.insert("end", f)
        if not excluded_files:
            excluded_box.insert("end", "(لا يوجد ملفات مستبعدة)")

        # تحذيرات التعارض
        if conflicts:
            warn_frame = tk.Frame(self, bg="#ffe5e5")
            warn_frame.pack(fill="x", padx=10, pady=5)
            tk.Label(warn_frame, text="⚠ تحذير: تعارضات محتملة في الأسماء:",
                     bg="#ffe5e5", fg="#a30000", font=("Arial", 10, "bold")).pack(anchor="e", padx=5, pady=2)
            for c in conflicts:
                tk.Label(warn_frame, text=f"- {c}", bg="#ffe5e5", fg="#a30000").pack(anchor="e", padx=15)

        tk.Label(self, text=ATTRIBUTION_TEXT, fg="#555").pack(pady=8)
        tk.Button(self, text="إغلاق", command=self.destroy).pack(pady=5)


# ============================================================================
# التطبيق الرئيسي
# ============================================================================

class PDFRenamerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("إعادة تسمية PDF + الترقيم الفوري التلقائي")
        self.root.geometry("980x720")

        # ---------------- الحالة الداخلية ----------------
        self.current_folder = os.getcwd()
        self.all_files = []          # كل ملفات PDF المكتشفة (ترتيب العرض الحالي)
        self.excluded = set()        # أسماء الملفات المستبعدة يدويًا
        self.last_anchor_index = None  # لأجل Shift+Click

        self.last_rename_map = []    # [(new_name, old_name), ...] لإمكانية التراجع
        self.undo_available = False

        self.manual_operation_lock = threading.Lock()  # لمنع تعارض الخيوط
        self.live_numbering_active = False
        self.live_numbering_job = None
        self.known_files_snapshot = set()  # آخر قائمة ملفات معروفة للمراقبة الفورية

        self.drag_start_index = None
        self.search_active_filter = ""

        self._build_ui()
        self._setup_dnd()
        self.scan_folder()

    # ------------------------------------------------------------------
    # بناء الواجهة
    # ------------------------------------------------------------------
    def _build_ui(self):
        # ---- شريط المجلد ----
        top_frame = tk.Frame(self.root)
        top_frame.pack(fill="x", padx=10, pady=6)

        tk.Label(top_frame, text="المجلد الحالي:", font=("Arial", 10, "bold")).pack(side="right", padx=4)
        self.folder_var = tk.StringVar(value=self.current_folder)
        tk.Entry(top_frame, textvariable=self.folder_var, state="readonly", justify="right").pack(
            side="right", fill="x", expand=True, padx=4)
        tk.Button(top_frame, text="اختيار مجلد آخر", command=self.choose_folder).pack(side="right", padx=4)
        tk.Button(top_frame, text="تحديث المسح", command=self.scan_folder).pack(side="right", padx=4)

        # ---- صندوق البحث ----
        search_frame = tk.Frame(self.root)
        search_frame.pack(fill="x", padx=10, pady=2)
        tk.Label(search_frame, text="بحث/فلترة:").pack(side="right", padx=4)
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search_change)
        tk.Entry(search_frame, textvariable=self.search_var, justify="right").pack(
            side="right", fill="x", expand=True, padx=4)

        # ---- تلميح الاختصارات ----
        hint = ("تلميح: نقرة+سحب لإعادة الترتيب | Ctrl+نقرة لاستبعاد/تضمين ملف | "
                "Shift+نقرة لاستبعاد/تضمين نطاق كامل (السحب والفلترة يتعطلان معًا أثناء البحث)")
        tk.Label(self.root, text=hint, fg="#0055aa", wraplength=940, justify="right").pack(
            fill="x", padx=10, pady=(0, 4))

        # ---- القائمة الرئيسية ----
        list_frame = tk.Frame(self.root)
        list_frame.pack(fill="both", expand=True, padx=10, pady=4)

        self.listbox = tk.Listbox(list_frame, selectmode="browse", activestyle="dotbox",
                                   font=("Arial", 11), height=15, justify="right")
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=vsb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.listbox.bind("<Button-1>", self._on_listbox_click)
        self.listbox.bind("<B1-Motion>", self._on_listbox_drag)
        self.listbox.bind("<ButtonRelease-1>", self._on_listbox_release)

        # ---- قسم نمط الاسم الجديد ----
        pattern_frame = tk.LabelFrame(self.root, text="نمط الاسم الجديد")
        pattern_frame.pack(fill="x", padx=10, pady=6)

        tk.Label(pattern_frame, text="النمط (استخدم {n} للرقم التسلسلي):").pack(side="right", padx=4, pady=4)
        self.pattern_var = tk.StringVar(value="{n}")
        self.pattern_var.trace_add("write", self._update_preview)
        tk.Entry(pattern_frame, textvariable=self.pattern_var, justify="left", width=25).pack(
            side="right", padx=4, pady=4)

        self.add_date_var = tk.BooleanVar(value=False)
        self.add_date_var.trace_add("write", lambda *a: self._update_preview())
        tk.Checkbutton(pattern_frame, text="إضافة التاريخ الحالي كبادئة (YYYY-MM-DD_)",
                        variable=self.add_date_var).pack(side="right", padx=10)

        tk.Label(pattern_frame, text="مثال مباشر:").pack(side="right", padx=4)
        self.preview_label_var = tk.StringVar(value="")
        tk.Label(pattern_frame, textvariable=self.preview_label_var, fg="#006600",
                 font=("Arial", 10, "bold")).pack(side="right", padx=4)

        # ---- الأزرار الرئيسية ----
        btn_frame = tk.Frame(self.root)
        btn_frame.pack(fill="x", padx=10, pady=6)

        tk.Button(btn_frame, text="معاينة", width=14, command=self.show_preview).pack(side="right", padx=3)
        tk.Button(btn_frame, text="تنفيذ إعادة التسمية", width=18, bg="#cce5ff",
                  command=self.execute_rename).pack(side="right", padx=3)
        self.undo_btn = tk.Button(btn_frame, text="تراجع عن آخر عملية", width=18,
                                   command=self.undo_last_rename, state="disabled")
        self.undo_btn.pack(side="right", padx=3)

        self.live_toggle_btn = tk.Button(btn_frame, text="بدء الترقيم الفوري", width=18,
                                          bg="#d4f7d4", command=self.toggle_live_numbering)
        self.live_toggle_btn.pack(side="right", padx=3)

        # ---- مؤشر وسجل الترقيم الفوري ----
        live_frame = tk.LabelFrame(self.root, text="حالة الترقيم الفوري التلقائي")
        live_frame.pack(fill="both", padx=10, pady=6)

        status_row = tk.Frame(live_frame)
        status_row.pack(fill="x")
        self.live_status_var = tk.StringVar(value="متوقفة")
        tk.Label(status_row, text="الحالة:").pack(side="right", padx=4)
        self.live_status_label = tk.Label(status_row, textvariable=self.live_status_var,
                                           fg="#aa0000", font=("Arial", 10, "bold"))
        self.live_status_label.pack(side="right", padx=4)

        self.live_log = tk.Listbox(live_frame, height=5, justify="right")
        self.live_log.pack(fill="x", padx=4, pady=4)

        if not DND_AVAILABLE:
            tk.Label(self.root, text="ملاحظة: مكتبة tkinterdnd2 غير مثبتة، لذلك خاصية السحب والإفلات "
                                      "من مستكشف الملفات غير مفعّلة في هذه النسخة (باقي الميزات تعمل بشكل كامل).",
                     fg="#aa6600", wraplength=940, justify="right").pack(fill="x", padx=10, pady=2)

        # ---- شريط الحالة السفلي ----
        self.status_var = tk.StringVar(value="جاهز.")
        status_bar = tk.Label(self.root, textvariable=self.status_var, bd=1, relief="sunken",
                               anchor="e", justify="right")
        status_bar.pack(fill="x", side="bottom")

        tk.Label(self.root, text=ATTRIBUTION_TEXT, fg="#555").pack(side="bottom", pady=3)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    # السحب والإفلات الخارجي (tkinterdnd2)
    # ------------------------------------------------------------------
    def _setup_dnd(self):
        if not DND_AVAILABLE:
            return
        try:
            self.listbox.drop_target_register(DND_FILES)
            self.listbox.dnd_bind("<<Drop>>", self._on_external_drop)
        except Exception:
            pass

    def _on_external_drop(self, event):
        """التعامل مع إفلات ملفات/مجلدات من خارج البرنامج."""
        try:
            raw_paths = self.root.tk.splitlist(event.data)
        except Exception:
            raw_paths = [event.data]

        added_any = False
        for path in raw_paths:
            path = path.strip("{}")
            if os.path.isdir(path):
                for f in list_pdf_files(path):
                    src = os.path.join(path, f)
                    dst = os.path.join(self.current_folder, f)
                    if self._safe_copy_external(src, dst):
                        added_any = True
            elif os.path.isfile(path) and path.lower().endswith(".pdf"):
                dst = os.path.join(self.current_folder, os.path.basename(path))
                if self._safe_copy_external(path, dst):
                    added_any = True

        if added_any:
            self.set_status("تم إضافة ملف/ملفات مسحوبة من خارج البرنامج.")
            self.scan_folder()
        else:
            self.set_status("لم تتم إضافة أي ملفات (قد تكون موجودة بالفعل أو غير PDF).")

    def _safe_copy_external(self, src, dst):
        """نقل ملف خارجي إلى المجلد الحالي باستخدام shutil.move بأمان."""
        try:
            if os.path.abspath(src) == os.path.abspath(dst):
                return False
            if os.path.exists(dst):
                base, ext = os.path.splitext(os.path.basename(dst))
                dst = os.path.join(self.current_folder, f"{base}_{uuid.uuid4().hex[:6]}{ext}")
            shutil.move(src, dst)
            return True
        except Exception as e:
            self.set_status(f"خطأ أثناء نقل ملف مسحوب: {e}")
            return False

    # ------------------------------------------------------------------
    # اختيار المجلد ومسحه
    # ------------------------------------------------------------------
    def choose_folder(self):
        folder = filedialog.askdirectory(initialdir=self.current_folder)
        if folder:
            self.current_folder = folder
            self.folder_var.set(folder)
            self.scan_folder()

    def scan_folder(self):
        """مسح المجلد في خيط منفصل لتجنب تجميد الواجهة."""
        self.set_status("جاري مسح المجلد...")
        threading.Thread(target=self._scan_folder_worker, daemon=True).start()

    def _scan_folder_worker(self):
        try:
            files = list_pdf_files(self.current_folder)
            files_sorted = sorted(files, key=natural_sort_key)
        except Exception as e:
            self.root.after(0, lambda: self.set_status(f"خطأ أثناء المسح: {e}"))
            return
        self.root.after(0, lambda: self._apply_scan_result(files_sorted))

    def _apply_scan_result(self, files_sorted):
        self.all_files = files_sorted
        # تنظيف المستبعدة من ملفات غير موجودة بعد
        self.excluded = {f for f in self.excluded if f in self.all_files}
        self.known_files_snapshot = set(self.all_files)
        self._refresh_listbox()
        self.set_status(f"تم العثور على {len(self.all_files)} ملف PDF.")

    # ------------------------------------------------------------------
    # عرض القائمة + الفلترة
    # ------------------------------------------------------------------
    def _refresh_listbox(self):
        self.listbox.delete(0, "end")
        query = self.search_var.get().strip().lower()
        self.search_active_filter = query
        for f in self.all_files:
            if query and query not in f.lower():
                continue
            self.listbox.insert("end", f)
        self._repaint_colors()
        self._update_preview()

    def _repaint_colors(self):
        for i in range(self.listbox.size()):
            name = self.listbox.get(i)
            if name in self.excluded:
                self.listbox.itemconfig(i, bg="#ffcccc", fg="#660000")
            else:
                self.listbox.itemconfig(i, bg="white", fg="black")

    def _on_search_change(self, *args):
        self._refresh_listbox()

    def _is_filtering_active(self):
        return bool(self.search_var.get().strip())

    # ------------------------------------------------------------------
    # تفاعلات الماوس على القائمة: استبعاد / سحب وترتيب
    # ------------------------------------------------------------------
    def _on_listbox_click(self, event):
        index = self.listbox.nearest(event.y)
        if index < 0 or index >= self.listbox.size():
            return

        ctrl_pressed = bool(event.state & 0x0004)
        shift_pressed = bool(event.state & 0x0001)

        if ctrl_pressed:
            self._toggle_exclude(index)
            self.last_anchor_index = index
            return "break"
        elif shift_pressed and self.last_anchor_index is not None:
            self._toggle_exclude_range(self.last_anchor_index, index)
            return "break"
        else:
            self.last_anchor_index = index
            # تحضير للسحب فقط إن لم تكن الفلترة مفعّلة
            if not self._is_filtering_active():
                self.drag_start_index = index
            else:
                self.drag_start_index = None

    def _on_listbox_drag(self, event):
        if self.drag_start_index is None or self._is_filtering_active():
            return
        new_index = self.listbox.nearest(event.y)
        if new_index < 0 or new_index >= self.listbox.size():
            return
        if new_index != self.drag_start_index:
            name = self.listbox.get(self.drag_start_index)
            self.listbox.delete(self.drag_start_index)
            self.listbox.insert(new_index, name)
            self._repaint_colors()
            self.drag_start_index = new_index
            self._sync_all_files_order_from_listbox()
            self._update_preview()

    def _on_listbox_release(self, event):
        self.drag_start_index = None

    def _sync_all_files_order_from_listbox(self):
        """مزامنة ترتيب all_files مع الترتيب الحالي المعروض في القائمة (عند عدم وجود فلترة)."""
        if self._is_filtering_active():
            return
        self.all_files = [self.listbox.get(i) for i in range(self.listbox.size())]

    def _toggle_exclude(self, index):
        name = self.listbox.get(index)
        if name in self.excluded:
            self.excluded.discard(name)
        else:
            self.excluded.add(name)
        self._repaint_colors()
        self._update_preview()

    def _toggle_exclude_range(self, start, end):
        lo, hi = sorted((start, end))
        names = [self.listbox.get(i) for i in range(lo, hi + 1)]
        # إن كانت أغلب العناصر مستبعدة، نقوم بتضمينها جميعًا، وإلا نستبعدها جميعًا
        excluded_count = sum(1 for n in names if n in self.excluded)
        should_exclude = excluded_count < len(names) / 2
        for n in names:
            if should_exclude:
                self.excluded.add(n)
            else:
                self.excluded.discard(n)
        self._repaint_colors()
        self._update_preview()

    # ------------------------------------------------------------------
    # حساب خطة إعادة التسمية والمعاينة المباشرة
    # ------------------------------------------------------------------
    def _compute_rename_plan(self):
        """
        يحسب خطة إعادة التسمية بناءً على ترتيب القائمة الحالي (all_files)
        مع تجاهل الملفات المستبعدة. يعيد قائمة [(old_name, new_name), ...]
        """
        pattern = self.pattern_var.get()
        add_date = self.add_date_var.get()
        plan = []
        n = 1
        for f in self.all_files:
            if f in self.excluded:
                continue
            new_base = build_name_from_pattern(pattern, n, add_date)
            new_name = new_base + ".pdf"
            plan.append((f, new_name))
            n += 1
        return plan

    def _detect_conflicts(self, plan):
        """التحقق من تعارض أي اسم جديد مع اسم ملف مستبعد موجود فعليًا، أو تكرار أسماء جديدة."""
        conflicts = []
        new_names = [new for _, new in plan]
        excluded_names = self.excluded

        seen = {}
        for old, new in plan:
            seen.setdefault(new, []).append(old)
        for new, olds in seen.items():
            if len(olds) > 1:
                conflicts.append(f"تكرار الاسم الجديد '{new}' لأكثر من ملف: {', '.join(olds)}")

        for new in new_names:
            if new in excluded_names:
                conflicts.append(f"الاسم الجديد المقترح '{new}' يتطابق مع اسم ملف مستبعد موجود فعليًا!")
        return conflicts

    def _update_preview(self, *args):
        try:
            sample_name = build_name_from_pattern(self.pattern_var.get(), 1, self.add_date_var.get())
            self.preview_label_var.set(sample_name + ".pdf")
        except Exception:
            self.preview_label_var.set("(نمط غير صالح)")

    # ------------------------------------------------------------------
    # نافذة المعاينة الكاملة
    # ------------------------------------------------------------------
    def show_preview(self):
        if not self.all_files:
            messagebox.showinfo("معاينة", "لا توجد ملفات PDF لمعاينتها.")
            return
        plan = self._compute_rename_plan()
        conflicts = self._detect_conflicts(plan)
        excluded_list = sorted([f for f in self.all_files if f in self.excluded], key=natural_sort_key)
        PreviewWindow(self.root, plan, excluded_list, conflicts)

    # ------------------------------------------------------------------
    # تنفيذ إعادة التسمية الفعلية
    # ------------------------------------------------------------------
    def execute_rename(self):
        if not self.all_files:
            messagebox.showinfo("تنبيه", "لا توجد ملفات PDF لإعادة تسميتها.")
            return

        plan = self._compute_rename_plan()
        if not plan:
            messagebox.showinfo("تنبيه", "كل الملفات مستبعدة حاليًا، لا يوجد ما يُعاد تسميته.")
            return

        conflicts = self._detect_conflicts(plan)
        if conflicts:
            msg = "توجد تعارضات في الأسماء:\n" + "\n".join(conflicts) + "\n\nهل تريد المتابعة رغم ذلك؟"
            if not messagebox.askyesno("تحذير تعارض", msg):
                return

        if not messagebox.askyesno("تأكيد", f"سيتم إعادة تسمية {len(plan)} ملف. هل تريد المتابعة؟"):
            return

        self.set_status("جاري تنفيذ إعادة التسمية...")
        threading.Thread(target=self._execute_rename_worker, args=(plan,), daemon=True).start()

    def _execute_rename_worker(self, plan):
        # إيقاف الترقيم الفوري مؤقتًا لمنع تعارض الوصول لنفس الملفات
        with self.manual_operation_lock:
            errors = []
            successful_map = []  # [(new_name, old_name)]
            try:
                for old_name, new_name in plan:
                    old_path = os.path.join(self.current_folder, old_name)
                    new_path = os.path.join(self.current_folder, new_name)
                    if not os.path.exists(old_path):
                        errors.append(f"الملف '{old_name}' غير موجود (تم تجاوزه).")
                        continue
                    try:
                        if old_path == new_path:
                            successful_map.append((new_name, old_name))
                            continue
                        safe_two_phase_move(old_path, new_path)
                        successful_map.append((new_name, old_name))
                    except PermissionError:
                        errors.append(f"لا توجد صلاحية كافية لإعادة تسمية '{old_name}'.")
                    except FileNotFoundError:
                        errors.append(f"الملف '{old_name}' لم يُعثر عليه أثناء التنفيذ.")
                    except Exception as e:
                        errors.append(f"خطأ غير متوقع مع '{old_name}': {e}")
            except Exception as e:
                errors.append(f"خطأ عام أثناء إعادة التسمية: {e}")

        self.last_rename_map = successful_map
        self.undo_available = len(successful_map) > 0

        def finish():
            self.undo_btn.config(state=("normal" if self.undo_available else "disabled"))
            if errors:
                messagebox.showwarning("اكتمل مع وجود أخطاء", "\n".join(errors))
            self.set_status(f"تمت إعادة تسمية {len(successful_map)} ملف بنجاح.")
            self.scan_folder()

        self.root.after(0, finish)

    # ------------------------------------------------------------------
    # التراجع عن آخر عملية
    # ------------------------------------------------------------------
    def undo_last_rename(self):
        if not self.undo_available or not self.last_rename_map:
            messagebox.showinfo("تنبيه", "لا توجد عملية سابقة للتراجع عنها.")
            return
        if not messagebox.askyesno("تأكيد التراجع", "هل تريد التراجع عن آخر عملية إعادة تسمية؟"):
            return
        self.set_status("جاري التراجع عن آخر عملية...")
        threading.Thread(target=self._undo_worker, daemon=True).start()

    def _undo_worker(self):
        with self.manual_operation_lock:
            errors = []
            for new_name, old_name in self.last_rename_map:
                new_path = os.path.join(self.current_folder, new_name)
                old_path = os.path.join(self.current_folder, old_name)
                if not os.path.exists(new_path):
                    errors.append(f"تعذّر العثور على '{new_name}' للتراجع.")
                    continue
                try:
                    if new_path == old_path:
                        continue
                    safe_two_phase_move(new_path, old_path)
                except Exception as e:
                    errors.append(f"خطأ أثناء التراجع عن '{new_name}': {e}")

        def finish():
            self.last_rename_map = []
            self.undo_available = False
            self.undo_btn.config(state="disabled")
            if errors:
                messagebox.showwarning("اكتمل التراجع مع أخطاء", "\n".join(errors))
            self.set_status("تم التراجع عن آخر عملية إعادة تسمية.")
            self.scan_folder()

        self.root.after(0, finish)

    # ------------------------------------------------------------------
    # الترقيم الفوري التلقائي (Live Auto-Numbering)
    # ------------------------------------------------------------------
    def toggle_live_numbering(self):
        if self.live_numbering_active:
            self._stop_live_numbering()
        else:
            self._start_live_numbering()

    def _start_live_numbering(self):
        self.live_numbering_active = True
        self.live_status_var.set("نشطة الآن")
        self.live_status_label.config(fg="#007700")
        self.live_toggle_btn.config(text="إيقاف الترقيم الفوري", bg="#ffd9b3")
        # أخذ لقطة حالية لتفادي اعتبار الملفات الموجودة "جديدة"
        self.known_files_snapshot = set(list_pdf_files(self.current_folder))
        self._schedule_live_check()
        self._log_live(f"تم تفعيل الترقيم الفوري في {datetime.now().strftime('%H:%M:%S')}")

    def _stop_live_numbering(self):
        self.live_numbering_active = False
        self.live_status_var.set("متوقفة")
        self.live_status_label.config(fg="#aa0000")
        self.live_toggle_btn.config(text="بدء الترقيم الفوري", bg="#d4f7d4")
        if self.live_numbering_job is not None:
            try:
                self.root.after_cancel(self.live_numbering_job)
            except Exception:
                pass
            self.live_numbering_job = None
        self._log_live(f"تم إيقاف الترقيم الفوري في {datetime.now().strftime('%H:%M:%S')}")

    def _schedule_live_check(self):
        """جدولة دورة فحص جديدة كل 1.5 ثانية تقريبًا باستخدام root.after (دون أي مكتبة خارجية)."""
        if not self.live_numbering_active:
            return
        # تنفيذ الفحص الفعلي في خيط منفصل لتجنب تجميد الواجهة، ثم العودة للحلقة الرئيسية
        threading.Thread(target=self._live_check_worker, daemon=True).start()
        self.live_numbering_job = self.root.after(1500, self._schedule_live_check)

    def _live_check_worker(self):
        """
        دورة فحص واحدة: تكتشف الملفات الجديدة وتُرقّمها فوريًا.
        لا تُحترَم قائمة الاستبعاد اليدوية هنا حسب المواصفات.
        """
        # تجنّب التعارض مع عملية يدوية جارية (إعادة تسمية / تراجع)
        if not self.manual_operation_lock.acquire(blocking=False):
            return
        try:
            current_files = set(list_pdf_files(self.current_folder))
            new_files = current_files - self.known_files_snapshot
            if not new_files:
                self.known_files_snapshot = current_files
                return

            # ترتيب الملفات الجديدة بحسب وقت التعديل (افتراض عملي لترتيب "وقت الإضافة الفعلي")
            # ملاحظة: لا توجد طريقة مضمونة 100% لمعرفة لحظة "ظهور" الملف بدقة عبر Polling البسيط،
            # لذلك نعتمد على وقت آخر تعديل (mtime) كأقرب تقدير عملي لترتيب الدخول.
            def mtime_safe(fname):
                try:
                    return os.path.getmtime(os.path.join(self.current_folder, fname))
                except OSError:
                    return 0

            new_files_sorted = sorted(new_files, key=mtime_safe)

            for fname in new_files_sorted:
                full_path = os.path.join(self.current_folder, fname)
                if not os.path.exists(full_path):
                    continue
                # التحقق من استقرار حجم الملف (ليس قيد نسخ/تحميل)
                if not is_file_size_stable(full_path, wait_seconds=0.5):
                    # سيُعاد فحصه في الدورة التالية لأنه لم يُحدَّث في known_files_snapshot
                    continue
                self._rename_new_file_live(fname)
                # تحديث اللقطة فورًا بعد كل ملف لمنع إعادة معالجته
                self.known_files_snapshot.add(fname)

            # تحديث اللقطة الكاملة في النهاية لاستيعاب أي ملفات لم تُرقَّم بعد (لا تزال قيد النسخ)
            stable_known = set(self.known_files_snapshot)
            self.known_files_snapshot = (current_files - new_files) | stable_known

        except Exception as e:
            self.root.after(0, lambda: self.set_status(f"خطأ في الترقيم الفوري: {e}"))
        finally:
            self.manual_operation_lock.release()

    def _rename_new_file_live(self, fname):
        """إعادة تسمية ملف جديد مكتشف وفق أول رقم فاضٍ متاح، مع تطبيق نمط التسمية المخصص."""
        try:
            existing_files = list_pdf_files(self.current_folder)
            used_numbers = extract_existing_numbers(existing_files)
            n = first_available_gap(used_numbers, start=1)

            pattern = self.pattern_var.get()
            add_date = self.add_date_var.get()
            new_base = build_name_from_pattern(pattern, n, add_date)
            new_name = new_base + ".pdf"

            old_path = os.path.join(self.current_folder, fname)
            new_path = os.path.join(self.current_folder, new_name)

            if not os.path.exists(old_path):
                return
            if os.path.exists(new_path) and os.path.abspath(new_path) != os.path.abspath(old_path):
                # تجنّب الكتابة فوق ملف موجود فعليًا: نبحث عن رقم آخر فاضٍ
                used_numbers.add(n)
                n = first_available_gap(used_numbers, start=n + 1)
                new_base = build_name_from_pattern(pattern, n, add_date)
                new_name = new_base + ".pdf"
                new_path = os.path.join(self.current_folder, new_name)

            safe_two_phase_move(old_path, new_path)

            timestamp = datetime.now().strftime('%H:%M:%S')
            self.root.after(0, lambda: self._log_live(f"[{timestamp}] تمت إعادة تسمية '{fname}' → '{new_name}'"))
            self.root.after(0, self.scan_folder)
        except Exception as e:
            self.root.after(0, lambda: self._log_live(f"خطأ أثناء ترقيم '{fname}': {e}"))

    def _log_live(self, message):
        self.live_log.insert(0, message)
        if self.live_log.size() > 50:
            self.live_log.delete(50, "end")

    # ------------------------------------------------------------------
    # أدوات عامة
    # ------------------------------------------------------------------
    def set_status(self, message):
        self.status_var.set(message)

    def _on_close(self):
        # إيقاف الترقيم الفوري بالكامل عند إغلاق البرنامج (لا أثر متبقٍ)
        self.live_numbering_active = False
        if self.live_numbering_job is not None:
            try:
                self.root.after_cancel(self.live_numbering_job)
            except Exception:
                pass
        self.root.destroy()


# ============================================================================
# نقطة تشغيل البرنامج
# ============================================================================

def main():
    if DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()

    try:
        app = PDFRenamerApp(root)
    except Exception as e:
        messagebox.showerror("خطأ فادح", f"حدث خطأ أثناء تشغيل البرنامج:\n{e}")
        sys.exit(1)

    root.mainloop()


if __name__ == "__main__":
    main()

