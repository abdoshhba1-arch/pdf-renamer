#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF Bulk Renamer Pro v2
=========================
تطبيق سطح مكتب (Tkinter) لإعادة تسمية ملفات PDF دفعة واحدة بشكل تسلسلي،
مع مزايا إضافية:
  1) استبعاد الملفات بالماوس (نقرة/Ctrl+نقرة/Shift+نقرة) بدل كتابة الأسماء.
  2) زر "تراجع" يرجّع آخر عملية إعادة تسمية.
  3) نمط تسمية مخصص (بادئة/لاحقة + خيار إضافة التاريخ).
  4) سحب وإفلات ملفات/مجلدات من مستكشف الملفات مباشرة على نافذة البرنامج
     (يتطلب مكتبة tkinterdnd2 الخارجية - اختيارية، البرنامج يعمل بدونها أيضًا
     لكن بدون خاصية السحب والإفلات).
  5) إعادة ترتيب الملفات يدويًا بالسحب داخل القائمة (يحدد ترتيب الترقيم).
  8) صندوق بحث/فلترة فوق القائمة.

صُنع بواسطة عبدالله بن أخوك 🙂
"""

import os
import re
import shutil
import uuid
import threading
from datetime import datetime

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# محاولة استيراد مكتبة السحب والإفلات (اختيارية)
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
except ImportError:
    DND_AVAILABLE = False

APP_TITLE = "PDF Abdo"
CREDIT_TEXT = " 🙂 صُنع بواسطة عبدالله ابن أخوك 🙂"

EXCLUDED_BG, EXCLUDED_FG = "#ffd9d9", "#990000"
NORMAL_BG, NORMAL_FG = "#ffffff", "#000000"


# --------------------------------------------------------------------------- #
# دوال مساعدة عامة
# --------------------------------------------------------------------------- #

def get_default_folder() -> str:
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        return os.getcwd()


def natural_sort_key(filename: str):
    parts = re.split(r'(\d+)', filename)
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def list_pdf_files(folder: str):
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"المجلد غير موجود: {folder}")
    try:
        entries = os.listdir(folder)
    except PermissionError:
        raise PermissionError(f"لا توجد صلاحية كافية للوصول إلى المجلد: {folder}")
    pdf_files = [
        f for f in entries
        if os.path.isfile(os.path.join(folder, f)) and f.lower().endswith(".pdf")
    ]
    pdf_files.sort(key=natural_sort_key)
    return pdf_files


def sanitize_filename(name: str) -> str:
    """يحذف الرموز غير المسموحة في أسماء الملفات على ويندوز."""
    return re.sub(r'[\\/:*?"<>|]', "_", name)


# --------------------------------------------------------------------------- #
# التطبيق الرئيسي
# --------------------------------------------------------------------------- #

class PDFRenamerApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("740x680")
        self.root.minsize(620, 560)

        self.folder = get_default_folder()
        # self.order: الترتيب الحالي لكل الملفات (المرشحة للعرض)، بما فيها المستبعدة
        self.order = []
        # self.excluded: مجموعة أسماء الملفات المستبعدة من إعادة التسمية
        self.excluded = set()
        # self.file_sources: اسم الملف -> المسار الكامل الحالي على القرص
        self.file_sources = {}
        # خريطة: صف ظاهر في القائمة -> فهرس في self.order (تتأثر بالفلترة)
        self.visible_indices = []
        # بيانات السحب لإعادة الترتيب
        self.drag_start_view = None
        self.last_anchor_view = None
        # بيانات التراجع: قائمة (المسار بعد إعادة التسمية، المسار الأصلي قبلها)
        self.last_undo_data = None

        self._build_ui()
        self._scan_folder_async()

    # ----------------------------- بناء الواجهة ----------------------------- #

    def _build_ui(self):
        # --- شريط المجلد ---
        top = ttk.Frame(self.root, padding=(10, 10, 10, 4))
        top.pack(fill="x")
        ttk.Label(top, text="المجلد الحالي:", font=("Segoe UI", 9, "bold")).pack(side="right")
        self.folder_var = tk.StringVar(value=self.folder)
        ttk.Entry(top, textvariable=self.folder_var, justify="right", state="readonly").pack(
            side="right", fill="x", expand=True, padx=8)
        ttk.Button(top, text="اختيار مجلد...", command=self.browse_folder).pack(side="right")

        # --- صندوق البحث/الفلترة (ميزة 8) ---
        search_frame = ttk.Frame(self.root, padding=(10, 0, 10, 4))
        search_frame.pack(fill="x")
        ttk.Label(search_frame, text="بحث:", font=("Segoe UI", 9, "bold")).pack(side="right")
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *a: self._refresh_listbox())
        ttk.Entry(search_frame, textvariable=self.filter_var, justify="right").pack(
            side="right", fill="x", expand=True, padx=8)

        # --- معلومات وعدد ---
        info = ttk.Frame(self.root, padding=(10, 0, 10, 2))
        info.pack(fill="x")
        self.count_label = ttk.Label(info, text="جاري المسح...", anchor="e", justify="right")
        self.count_label.pack(fill="x")

        hint = ttk.Label(
            self.root,
            text="نقرة + سحب = إعادة ترتيب  |  Ctrl+نقرة = استبعاد/تضمين ملف  |  Shift+نقرة = استبعاد نطاق",
            anchor="e", justify="right", foreground="#555555", font=("Segoe UI", 8, "italic"),
            padding=(10, 0, 10, 4)
        )
        hint.pack(fill="x")
        if not DND_AVAILABLE:
            ttk.Label(
                self.root,
                text="(السحب والإفلات من مستكشف الملفات غير مفعّل في هذه النسخة)",
                anchor="e", justify="right", foreground="#aa6600", font=("Segoe UI", 8),
                padding=(10, 0, 10, 2)
            ).pack(fill="x")

        # --- القائمة ---
        list_frame = ttk.Frame(self.root, padding=(10, 0, 10, 4))
        list_frame.pack(fill="both", expand=True)
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        self.listbox = tk.Listbox(
            list_frame, selectmode="browse", activestyle="none", exportselection=False,
            yscrollcommand=scrollbar.set, font=("Consolas", 10), justify="right",
            bg=NORMAL_BG, fg=NORMAL_FG,
        )
        # تحييد لون التحديد الافتراضي بحيث يظهر فقط تلوينُنا الخاص (مستبعد/عادي)
        self.listbox.configure(selectbackground=NORMAL_BG, selectforeground=NORMAL_FG)
        scrollbar.config(command=self.listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.listbox.pack(side="right", fill="both", expand=True)

        self.listbox.bind("<Button-1>", self._on_list_press)
        self.listbox.bind("<B1-Motion>", self._on_list_drag)
        self.listbox.bind("<ButtonRelease-1>", self._on_list_release)

        # تفعيل السحب والإفلات من مستكشف الملفات إن كانت المكتبة متاحة
        if DND_AVAILABLE:
            self.listbox.drop_target_register(DND_FILES)
            self.listbox.dnd_bind("<<Drop>>", self._on_drop_files)

        # --- نمط التسمية (ميزة 3) ---
        pattern_frame = ttk.LabelFrame(self.root, text="نمط الاسم الجديد", padding=8)
        pattern_frame.pack(fill="x", padx=10, pady=(0, 4))

        row1 = ttk.Frame(pattern_frame)
        row1.pack(fill="x")
        ttk.Label(row1, text="استخدم {n} لمكان الرقم التسلسلي:").pack(side="right")
        self.pattern_var = tk.StringVar(value="{n}")
        ttk.Entry(row1, textvariable=self.pattern_var, justify="left", width=25).pack(
            side="right", padx=8)

        row2 = ttk.Frame(pattern_frame)
        row2.pack(fill="x", pady=(4, 0))
        self.use_date_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row2, text="إضافة التاريخ الحالي كبادئة (YYYY-MM-DD_)",
                         variable=self.use_date_var).pack(side="right")
        self.example_label = ttk.Label(row2, text="", foreground="#1a5d1a")
        self.example_label.pack(side="left")
        self.pattern_var.trace_add("write", lambda *a: self._update_example())
        self.use_date_var.trace_add("write", lambda *a: self._update_example())
        self._update_example()

        # --- الأزرار ---
        btns = ttk.Frame(self.root, padding=(10, 4, 10, 4))
        btns.pack(fill="x")
        ttk.Button(btns, text="تحديث المسح", command=self._scan_folder_async).pack(side="right", padx=4)
        ttk.Button(btns, text="معاينة", command=self.preview_rename).pack(side="right", padx=4)
        self.rename_btn = ttk.Button(btns, text="تنفيذ إعادة التسمية", command=self.confirm_and_rename)
        self.rename_btn.pack(side="right", padx=4)
        self.undo_btn = ttk.Button(btns, text="تراجع عن آخر عملية", command=self.undo_last_rename,
                                    state="disabled")
        self.undo_btn.pack(side="right", padx=4)

        # --- شريط الحالة ---
        status = ttk.Frame(self.root, padding=(10, 4, 10, 4))
        status.pack(fill="x")
        self.status_var = tk.StringVar(value="جاهز.")
        ttk.Label(status, textvariable=self.status_var, anchor="e", justify="right",
                  foreground="#1a5d1a", font=("Segoe UI", 9, "bold")).pack(fill="x")

        ttk.Label(self.root, text=CREDIT_TEXT, anchor="center",
                  font=("Segoe UI", 9, "italic"), foreground="#666666").pack(fill="x", pady=(0, 6))

    def _update_example(self):
        try:
            example = self._compute_new_name(self.pattern_var.get(), 1, self.use_date_var.get())
            self.example_label.config(text=f"مثال: {example}")
        except Exception:
            self.example_label.config(text="")

    # ----------------------------- المسح ----------------------------- #

    def browse_folder(self):
        chosen = filedialog.askdirectory(initialdir=self.folder, title="اختر مجلدًا يحتوي على ملفات PDF")
        if chosen:
            self.folder = chosen
            self.folder_var.set(self.folder)
            self._scan_folder_async()

    def _scan_folder_async(self):
        self.status_var.set("جاري المسح عن ملفات PDF...")
        self.rename_btn.config(state="disabled")
        threading.Thread(target=self._scan_folder_worker, daemon=True).start()

    def _scan_folder_worker(self):
        try:
            files = list_pdf_files(self.folder)
            error = None
        except Exception as e:
            files = []
            error = str(e)
        self.root.after(0, lambda: self._scan_folder_done(files, error))

    def _scan_folder_done(self, files, error):
        self.order = list(files)
        self.excluded = set()
        self.file_sources = {f: os.path.join(self.folder, f) for f in files}
        self.filter_var.set("")
        self._refresh_listbox()
        self.rename_btn.config(state="normal")

        if error:
            messagebox.showerror("خطأ في المسح", error)
            self.status_var.set("فشل المسح.")
            self.count_label.config(text="تعذر مسح المجلد.")
            return

        if not self.order:
            self.status_var.set("لا توجد ملفات PDF في هذا المجلد.")
            self.count_label.config(text="0 ملف PDF تم العثور عليه.")
        else:
            self.status_var.set("تم المسح بنجاح.")
            self.count_label.config(text=f"تم العثور على {len(self.order)} ملف PDF.")

    # ----------------------------- العرض والتلوين ----------------------------- #

    def _refresh_listbox(self):
        filt = self.filter_var.get().strip().lower()
        self.listbox.delete(0, "end")
        self.visible_indices = []
        for i, fname in enumerate(self.order):
            if filt and filt not in fname.lower():
                continue
            self.visible_indices.append(i)
            self.listbox.insert("end", fname)
            row = self.listbox.size() - 1
            if fname in self.excluded:
                self.listbox.itemconfig(row, {"bg": EXCLUDED_BG, "fg": EXCLUDED_FG})
            else:
                self.listbox.itemconfig(row, {"bg": NORMAL_BG, "fg": NORMAL_FG})

    # ----------------------------- التفاعل بالماوس (ميزة 1 و 5) ----------------------------- #

    def _on_list_press(self, event):
        view_idx = self.listbox.nearest(event.y)
        if view_idx < 0 or view_idx >= len(self.visible_indices):
            return "break"

        ctrl = bool(event.state & 0x4)
        shift = bool(event.state & 0x1)

        if ctrl:
            self._toggle_exclude(view_idx)
            self.last_anchor_view = view_idx
            self.drag_start_view = None
            return "break"

        if shift and self.last_anchor_view is not None:
            self._toggle_exclude_range(self.last_anchor_view, view_idx)
            self.drag_start_view = None
            return "break"

        # بدون أي مفتاح إضافي: ابدأ سحب لإعادة الترتيب (فقط إذا لا يوجد فلتر نشط)
        self.last_anchor_view = view_idx
        if self.filter_var.get().strip():
            self.drag_start_view = None
        else:
            self.drag_start_view = view_idx
        return "break"

    def _on_list_drag(self, event):
        if self.drag_start_view is None:
            return "break"
        view_idx = self.listbox.nearest(event.y)
        if view_idx == self.drag_start_view or view_idx < 0 or view_idx >= len(self.order):
            return "break"
        # بدون فلتر نشط: الفهرس الظاهر = الفهرس الحقيقي في self.order
        fname = self.order.pop(self.drag_start_view)
        self.order.insert(view_idx, fname)
        self.drag_start_view = view_idx
        self._refresh_listbox()
        return "break"

    def _on_list_release(self, event):
        self.drag_start_view = None
        return "break"

    def _toggle_exclude(self, view_idx):
        real_idx = self.visible_indices[view_idx]
        fname = self.order[real_idx]
        if fname in self.excluded:
            self.excluded.discard(fname)
        else:
            self.excluded.add(fname)
        self._refresh_listbox()

    def _toggle_exclude_range(self, view_a, view_b):
        lo, hi = sorted((view_a, view_b))
        # نحدد الحالة الهدف بناءً على الملف عند نقطة النقر الجديدة
        target_real = self.visible_indices[view_b]
        target_fname = self.order[target_real]
        make_excluded = target_fname not in self.excluded
        for v in range(lo, hi + 1):
            real_idx = self.visible_indices[v]
            fname = self.order[real_idx]
            if make_excluded:
                self.excluded.add(fname)
            else:
                self.excluded.discard(fname)
        self._refresh_listbox()

    # ----------------------------- السحب والإفلات من الإكسبلورر (ميزة 4) ----------------------------- #

    def _on_drop_files(self, event):
        try:
            paths = self.root.tk.splitlist(event.data)
        except Exception:
            paths = []

        added = 0
        for p in paths:
            p = p.strip("{}")  # ويندوز يضيف أقواس حول المسارات التي فيها مسافات
            if os.path.isdir(p):
                try:
                    for f in list_pdf_files(p):
                        if self._add_dropped_file(os.path.join(p, f)):
                            added += 1
                except Exception:
                    pass
            elif os.path.isfile(p) and p.lower().endswith(".pdf"):
                if self._add_dropped_file(p):
                    added += 1

        if added:
            self._refresh_listbox()
            self.count_label.config(text=f"تم العثور على {len(self.order)} ملف PDF.")
            self.status_var.set(f"تمت إضافة {added} ملف عن طريق السحب والإفلات.")
        else:
            self.status_var.set("لم يتم العثور على ملفات PDF صالحة في العناصر المسحوبة.")

    def _add_dropped_file(self, full_path: str) -> bool:
        fname = os.path.basename(full_path)
        if fname in self.order:
            return False  # تجاهل التكرار بنفس الاسم
        self.order.append(fname)
        self.file_sources[fname] = full_path
        return True

    # ----------------------------- حساب الاسم الجديد ----------------------------- #

    def _compute_new_name(self, pattern: str, n: int, use_date: bool) -> str:
        pattern = pattern if pattern.strip() else "{n}"
        base = pattern if "{n}" in pattern else pattern + "{n}"
        name = base.replace("{n}", str(n))
        name = re.sub(r"\.pdf$", "", name, flags=re.IGNORECASE)
        name = sanitize_filename(name)
        if use_date:
            name = datetime.now().strftime("%Y-%m-%d_") + name
        return name + ".pdf"

    def _compute_mapping(self):
        remaining = [f for f in self.order if f not in self.excluded]
        pattern = self.pattern_var.get()
        use_date = self.use_date_var.get()
        mapping = []
        for idx, old in enumerate(remaining, start=1):
            new = self._compute_new_name(pattern, idx, use_date)
            mapping.append((old, new))
        return mapping

    def _find_conflicts(self, mapping):
        excluded_lower = {n.lower() for n in self.excluded}
        return [new for _, new in mapping if new.lower() in excluded_lower]

    # ----------------------------- المعاينة ----------------------------- #

    def preview_rename(self):
        if not self.order:
            messagebox.showinfo(APP_TITLE, "لا توجد ملفات PDF لمعاينتها.")
            return

        mapping = self._compute_mapping()
        conflicts = self._find_conflicts(mapping)

        win = tk.Toplevel(self.root)
        win.title("معاينة إعادة التسمية")
        win.geometry("520x480")
        win.transient(self.root)

        ttk.Label(win, text="معاينة العملية", font=("Segoe UI", 11, "bold"), anchor="center").pack(
            fill="x", pady=(10, 5))

        text = tk.Text(win, wrap="word", font=("Consolas", 10))
        text.pack(fill="both", expand=True, padx=12, pady=6)
        text.tag_configure("right", justify="right")

        text.insert("end", "── الملفات التي ستُعاد تسميتها (بترتيبها الحالي) ──\n", "right")
        if mapping:
            for old, new in mapping:
                text.insert("end", f"{old}   →   {new}\n", "right")
        else:
            text.insert("end", "(لا توجد ملفات لإعادة تسميتها)\n", "right")

        text.insert("end", "\n── الملفات المستبعدة (لن تتغير) ──\n", "right")
        if self.excluded:
            for name in sorted(self.excluded, key=natural_sort_key):
                text.insert("end", f"{name}\n", "right")
        else:
            text.insert("end", "(لا توجد ملفات مستبعدة)\n", "right")

        if conflicts:
            text.insert("end", "\n⚠ تعارض: الأسماء الجديدة التالية تتطابق مع ملفات مستبعدة:\n", "right")
            for c in conflicts:
                text.insert("end", f"{c}\n", "right")

        text.config(state="disabled")
        ttk.Button(win, text="إغلاق", command=win.destroy).pack(pady=8)

    # ----------------------------- التنفيذ ----------------------------- #

    def confirm_and_rename(self):
        if not self.order:
            messagebox.showinfo(APP_TITLE, "لا توجد ملفات PDF لإعادة تسميتها.")
            return

        mapping = self._compute_mapping()
        if not mapping:
            messagebox.showinfo(APP_TITLE, "جميع الملفات مستبعدة، لا يوجد ما يتم إعادة تسميته.")
            return

        conflicts = self._find_conflicts(mapping)
        if conflicts:
            messagebox.showerror(
                APP_TITLE,
                "تعذر إعادة التسمية بسبب تعارض الأسماء مع ملفات مستبعدة:\n" + "\n".join(conflicts)
            )
            return

        confirmed = messagebox.askyesno(
            APP_TITLE,
            f"سيتم إعادة تسمية {len(mapping)} ملف PDF.\n"
            f"عدد الملفات المستبعدة (لن تتغير): {len(self.excluded)}\n\n"
            "هل تريد المتابعة؟ (تقدر تستخدم زر 'تراجع' بعد التنفيذ لو غيرت رأيك)"
        )
        if not confirmed:
            return

        self.rename_btn.config(state="disabled")
        self.undo_btn.config(state="disabled")
        self.status_var.set("جاري إعادة التسمية...")
        threading.Thread(target=self._rename_worker, args=(mapping,), daemon=True).start()

    def _rename_worker(self, mapping):
        renamed_count = 0
        errors = []
        undo_data = []  # (المسار النهائي بعد إعادة التسمية، المسار الأصلي قبلها)

        try:
            temp_map = []  # (مسار مؤقت, اسم جديد نهائي, مسار أصلي قديم)
            for old, new in mapping:
                src = self.file_sources.get(old, os.path.join(self.folder, old))
                if not os.path.isfile(src):
                    errors.append(f"الملف غير موجود: {old}")
                    continue
                old_basename = os.path.basename(src)
                if old_basename == new:
                    renamed_count += 1
                    undo_data.append((src, src))
                    continue
                temp_name = f"~tmp_{uuid.uuid4().hex}.pdf"
                temp_path = os.path.join(self.folder, temp_name)
                shutil.move(src, temp_path)
                temp_map.append((temp_path, new, src))

            for temp_path, new, original_src in temp_map:
                final_path = os.path.join(self.folder, new)
                shutil.move(temp_path, final_path)
                renamed_count += 1
                undo_data.append((final_path, original_src))

        except PermissionError as e:
            errors.append(f"خطأ في الأذونات: {e}")
        except FileNotFoundError as e:
            errors.append(f"ملف غير موجود: {e}")
        except OSError as e:
            errors.append(f"خطأ في نظام الملفات: {e}")
        except Exception as e:
            errors.append(f"خطأ غير متوقع: {e}")

        self.root.after(0, lambda: self._rename_done(renamed_count, errors, undo_data))

    def _rename_done(self, renamed_count, errors, undo_data):
        self.rename_btn.config(state="normal")

        if errors:
            messagebox.showerror(APP_TITLE, "حدثت أخطاء خلال إعادة التسمية:\n" + "\n".join(errors))
            self.status_var.set("اكتملت العملية مع وجود أخطاء.")
        else:
            messagebox.showinfo(
                APP_TITLE,
                f"تمت العملية بنجاح ✅\n\n"
                f"عدد الملفات التي أُعيدت تسميتها: {renamed_count}\n"
                f"عدد الملفات المستبعدة (دون تغيير): {len(self.excluded)}"
            )
            self.status_var.set(f"تم! {renamed_count} ملف أُعيد تسميته.")

        if undo_data:
            self.last_undo_data = undo_data
            self.undo_btn.config(state="normal")

        self._scan_folder_async()

    # ----------------------------- التراجع (ميزة 2) ----------------------------- #

    def undo_last_rename(self):
        if not self.last_undo_data:
            messagebox.showinfo(APP_TITLE, "لا توجد عملية سابقة للتراجع عنها.")
            return

        confirmed = messagebox.askyesno(
            APP_TITLE, "هل تريد التراجع عن آخر عملية إعادة تسمية وإرجاع الأسماء الأصلية؟"
        )
        if not confirmed:
            return

        self.undo_btn.config(state="disabled")
        self.status_var.set("جاري التراجع...")
        threading.Thread(target=self._undo_worker, args=(self.last_undo_data,), daemon=True).start()

    def _undo_worker(self, undo_data):
        restored = 0
        errors = []
        try:
            temp_map = []
            for current_path, original_path in undo_data:
                if current_path == original_path or not os.path.isfile(current_path):
                    continue
                temp_name = f"~tmp_{uuid.uuid4().hex}.pdf"
                temp_path = os.path.join(os.path.dirname(current_path), temp_name)
                shutil.move(current_path, temp_path)
                temp_map.append((temp_path, original_path))

            for temp_path, original_path in temp_map:
                os.makedirs(os.path.dirname(original_path), exist_ok=True)
                shutil.move(temp_path, original_path)
                restored += 1
        except Exception as e:
            errors.append(f"خطأ خلال التراجع: {e}")

        self.root.after(0, lambda: self._undo_done(restored, errors))

    def _undo_done(self, restored, errors):
        self.last_undo_data = None
        if errors:
            messagebox.showerror(APP_TITLE, "\n".join(errors))
            self.status_var.set("التراجع اكتمل مع وجود أخطاء.")
        else:
            messagebox.showinfo(APP_TITLE, f"تم التراجع بنجاح، تمت استعادة {restored} ملف لاسمه الأصلي.")
            self.status_var.set("تم التراجع بنجاح.")
        self._scan_folder_async()


# --------------------------------------------------------------------------- #
# نقطة الدخول
# --------------------------------------------------------------------------- #

def main():
    if DND_AVAILABLE:
        root = TkinterDnD.Tk()
    else:
        root = tk.Tk()

    try:
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass

    PDFRenamerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
