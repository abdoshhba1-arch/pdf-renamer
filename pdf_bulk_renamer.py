#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF Bulk Renamer Pro
=====================
تطبيق سطح مكتب (Tkinter) لإعادة تسمية ملفات PDF دفعة واحدة بشكل تسلسلي
(1.pdf, 2.pdf, 3.pdf ...) مع إمكانية استبعاد ملفات محددة من إعادة التسمية.

- يستخدم فقط مكتبة بايثون القياسية (tkinter, os, re, shutil, threading).
- جاهز للتشغيل مباشرة: python pdf_bulk_renamer.py

صُنع بواسطة عبدالله بن أخوك 🙂
"""

import os
import re
import sys
import uuid
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

APP_TITLE = "PDF Bulk Renamer Pro"
CREDIT_TEXT = "صُنع بواسطة عبدالله بن أخوك 🙂"


# --------------------------------------------------------------------------- #
# دوال مساعدة (منطق عام لا يعتمد على واجهة المستخدم)
# --------------------------------------------------------------------------- #

def get_default_folder() -> str:
    """
    يحدد المجلد الافتراضي وهو المجلد الذي يوجد فيه هذا البرنامج النصي.
    في حال تشغيله من بيئة لا تحدد __file__ بشكل موثوق، يتم استخدام مجلد العمل الحالي.
    """
    try:
        return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        return os.getcwd()


def natural_sort_key(filename: str):
    """
    مفتاح فرز "طبيعي" (Natural Sort) يقسم اسم الملف إلى أجزاء نصية وأرقام
    بحيث يتم ترتيب "file2.pdf" قبل "file10.pdf" بدلاً من الترتيب الأبجدي الحرفي.
    """
    parts = re.split(r'(\d+)', filename)
    return [int(part) if part.isdigit() else part.lower() for part in parts]


def list_pdf_files(folder: str):
    """
    يمسح المجلد المحدد ويعيد قائمة بأسماء ملفات PDF فقط (بدون المسار الكامل)
    مرتبة ترتيبًا طبيعيًا. يتعامل بأمان مع أخطاء الأذونات أو المجلدات غير الموجودة.
    """
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


def strip_extension(filename: str) -> str:
    """يحذف امتداد .pdf (بدون اعتبار لحالة الأحرف) من اسم الملف."""
    if filename.lower().endswith(".pdf"):
        return filename[:-4]
    return filename


# --------------------------------------------------------------------------- #
# التطبيق الرئيسي
# --------------------------------------------------------------------------- #

class PDFRenamerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("680x560")
        self.root.minsize(560, 460)

        # الحالة الداخلية للتطبيق
        self.folder = get_default_folder()
        self.pdf_files = []          # كل ملفات PDF المكتشفة (مرتبة طبيعيًا)
        self.excluded_names = set()  # أسماء الملفات المستبعدة (بامتداد .pdf الكامل)

        self._build_ui()
        self._scan_folder_async()

    # ----------------------------- بناء الواجهة ----------------------------- #

    def _build_ui(self):
        # --- شريط المجلد العلوي ---
        top_frame = ttk.Frame(self.root, padding=(10, 10, 10, 5))
        top_frame.pack(fill="x")

        ttk.Label(top_frame, text="المجلد الحالي:", font=("Segoe UI", 9, "bold")).pack(side="right")
        self.folder_var = tk.StringVar(value=self.folder)
        folder_entry = ttk.Entry(top_frame, textvariable=self.folder_var, justify="right", state="readonly")
        folder_entry.pack(side="right", fill="x", expand=True, padx=8)

        ttk.Button(top_frame, text="اختيار مجلد...", command=self.browse_folder).pack(side="right")

        # --- عنوان وعدد الملفات ---
        info_frame = ttk.Frame(self.root, padding=(10, 0, 10, 5))
        info_frame.pack(fill="x")
        self.count_label = ttk.Label(info_frame, text="جاري المسح...", anchor="e", justify="right")
        self.count_label.pack(fill="x")

        # --- قائمة عرض ملفات PDF ---
        list_frame = ttk.Frame(self.root, padding=(10, 0, 10, 5))
        list_frame.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(list_frame, orient="vertical")
        self.listbox = tk.Listbox(
            list_frame, selectmode="extended", activestyle="dotbox",
            yscrollcommand=scrollbar.set, font=("Consolas", 10), justify="right"
        )
        scrollbar.config(command=self.listbox.yview)
        scrollbar.pack(side="right", fill="y")
        self.listbox.pack(side="right", fill="both", expand=True)

        # --- شريط الأزرار ---
        btn_frame = ttk.Frame(self.root, padding=(10, 5, 10, 5))
        btn_frame.pack(fill="x")

        ttk.Button(btn_frame, text="تحديث المسح", command=self._scan_folder_async).pack(side="right", padx=4)
        ttk.Button(btn_frame, text="استبعاد ملفات", command=self.exclude_files_dialog).pack(side="right", padx=4)
        ttk.Button(btn_frame, text="معاينة", command=self.preview_rename).pack(side="right", padx=4)
        self.rename_btn = ttk.Button(btn_frame, text="تنفيذ إعادة التسمية", command=self.confirm_and_rename)
        self.rename_btn.pack(side="right", padx=4)

        # --- شريط الحالة ---
        status_frame = ttk.Frame(self.root, padding=(10, 5, 10, 5))
        status_frame.pack(fill="x")
        self.status_var = tk.StringVar(value="جاهز.")
        ttk.Label(status_frame, textvariable=self.status_var, anchor="e", justify="right",
                  foreground="#1a5d1a", font=("Segoe UI", 9, "bold")).pack(fill="x")

        # --- إسناد المُنشئ ---
        credit_frame = ttk.Frame(self.root, padding=(10, 0, 10, 8))
        credit_frame.pack(fill="x")
        ttk.Label(credit_frame, text=CREDIT_TEXT, anchor="center",
                  font=("Segoe UI", 9, "italic"), foreground="#666666").pack(fill="x")

    # ----------------------------- المسح والعرض ----------------------------- #

    def browse_folder(self):
        chosen = filedialog.askdirectory(initialdir=self.folder, title="اختر مجلدًا يحتوي على ملفات PDF")
        if chosen:
            self.folder = chosen
            self.folder_var.set(self.folder)
            self._scan_folder_async()

    def _scan_folder_async(self):
        """يشغّل عملية المسح في خيط منفصل لمنع تجمد الواجهة الرسومية."""
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
        self.pdf_files = files
        self.excluded_names = set()  # إعادة تعيين الاستبعادات عند كل مسح جديد
        self._refresh_listbox()
        self.rename_btn.config(state="normal")

        if error:
            messagebox.showerror("خطأ في المسح", error)
            self.status_var.set("فشل المسح.")
            self.count_label.config(text="تعذر مسح المجلد.")
            return

        if not self.pdf_files:
            self.status_var.set("لا توجد ملفات PDF في هذا المجلد.")
            self.count_label.config(text="0 ملف PDF تم العثور عليه.")
        else:
            self.status_var.set("تم المسح بنجاح.")
            self.count_label.config(text=f"تم العثور على {len(self.pdf_files)} ملف PDF.")

    def _refresh_listbox(self):
        self.listbox.delete(0, "end")
        for f in self.pdf_files:
            tag = "  [مستبعد]" if f in self.excluded_names else ""
            self.listbox.insert("end", f"{f}{tag}")

    # ----------------------------- الاستبعاد ----------------------------- #

    def exclude_files_dialog(self):
        if not self.pdf_files:
            messagebox.showinfo(APP_TITLE, "لا توجد ملفات PDF لاستبعادها.")
            return

        wants_exclude = messagebox.askyesno(
            APP_TITLE, "هل تريد استبعاد أي ملفات من إعادة التسمية؟"
        )
        if not wants_exclude:
            self.excluded_names = set()
            self._refresh_listbox()
            return

        count = simpledialog.askinteger(
            APP_TITLE, "كم عدد الملفات التي تريد استبعادها؟",
            minvalue=1, maxvalue=len(self.pdf_files), parent=self.root
        )
        if not count:
            return  # المستخدم أغلق الحوار أو أدخل قيمة غير صالحة

        self._open_exclude_entry_window(count)

    def _open_exclude_entry_window(self, count: int):
        """نافذة بها عدد من حقول الإدخال يدخل المستخدم فيها أسماء الملفات المراد استبعادها."""
        win = tk.Toplevel(self.root)
        win.title("أسماء الملفات المستبعدة")
        win.geometry("420x" + str(min(60 + count * 36 + 90, 560)))
        win.transient(self.root)
        win.grab_set()

        ttk.Label(
            win, text="أدخل أسماء الملفات بدون امتداد .pdf (مثال: report_final)",
            wraplength=380, justify="right", anchor="e"
        ).pack(fill="x", padx=12, pady=(12, 8))

        canvas_frame = ttk.Frame(win)
        canvas_frame.pack(fill="both", expand=True, padx=12)

        entries = []
        for i in range(count):
            row = ttk.Frame(canvas_frame)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=f"ملف #{i + 1}:", width=10, anchor="e").pack(side="right")
            var = tk.StringVar()
            ent = ttk.Entry(row, textvariable=var, justify="right")
            ent.pack(side="right", fill="x", expand=True, padx=6)
            entries.append(var)

        def submit():
            raw_names = [v.get().strip() for v in entries if v.get().strip()]
            if not raw_names:
                messagebox.showwarning(APP_TITLE, "لم يتم إدخال أي اسم.", parent=win)
                return

            # بناء فهرس للأسماء الحالية (بدون الامتداد) لمطابقتها بدون حساسية لحالة الأحرف
            current_no_ext = {strip_extension(f).lower(): f for f in self.pdf_files}

            matched, unmatched = [], []
            for name in raw_names:
                clean = strip_extension(name).lower()
                if clean in current_no_ext:
                    matched.append(current_no_ext[clean])
                else:
                    unmatched.append(name)

            if unmatched:
                proceed = messagebox.askyesno(
                    APP_TITLE,
                    "الأسماء التالية لم يتم العثور عليها بين الملفات المكتشفة:\n"
                    + "\n".join(unmatched)
                    + "\n\nهل تريد الاستمرار وتجاهل هذه الأسماء؟",
                    parent=win
                )
                if not proceed:
                    return

            self.excluded_names = set(matched)
            self._refresh_listbox()
            self.status_var.set(f"تم استبعاد {len(matched)} ملف من إعادة التسمية.")
            win.destroy()

        btn_row = ttk.Frame(win, padding=10)
        btn_row.pack(fill="x")
        ttk.Button(btn_row, text="تأكيد", command=submit).pack(side="right", padx=4)
        ttk.Button(btn_row, text="إلغاء", command=win.destroy).pack(side="right", padx=4)

    # ----------------------------- المعاينة وإعادة التسمية ----------------------------- #

    def _compute_mapping(self):
        """
        يحسب خريطة إعادة التسمية: قائمة من (الاسم القديم، الاسم الجديد)
        للملفات غير المستبعدة، مرتبة ترتيبًا طبيعيًا ومرقّمة تسلسليًا.
        """
        remaining = [f for f in self.pdf_files if f not in self.excluded_names]
        remaining.sort(key=natural_sort_key)
        mapping = [(old, f"{idx}.pdf") for idx, old in enumerate(remaining, start=1)]
        return mapping

    def _find_conflicts(self, mapping):
        """
        يتحقق من وجود تعارض بين الأسماء الجديدة المقترحة وأسماء الملفات المستبعدة
        (لأن الملفات المستبعدة يجب ألا تُلمس أو تُستبدل أبدًا).
        """
        excluded_lower = {n.lower() for n in self.excluded_names}
        conflicts = [new for _, new in mapping if new.lower() in excluded_lower]
        return conflicts

    def preview_rename(self):
        if not self.pdf_files:
            messagebox.showinfo(APP_TITLE, "لا توجد ملفات PDF لمعاينتها.")
            return

        mapping = self._compute_mapping()
        conflicts = self._find_conflicts(mapping)

        win = tk.Toplevel(self.root)
        win.title("معاينة إعادة التسمية")
        win.geometry("500x480")
        win.transient(self.root)

        ttk.Label(win, text="معاينة العملية", font=("Segoe UI", 11, "bold"),
                  anchor="center").pack(fill="x", pady=(10, 5))

        text = tk.Text(win, wrap="word", font=("Consolas", 10))
        text.pack(fill="both", expand=True, padx=12, pady=6)

        text.tag_configure("right", justify="right")
        text.insert("end", "── الملفات التي ستُعاد تسميتها ──\n", "right")
        if mapping:
            for old, new in mapping:
                text.insert("end", f"{old}   →   {new}\n", "right")
        else:
            text.insert("end", "(لا توجد ملفات لإعادة تسميتها)\n", "right")

        text.insert("end", "\n── الملفات المستبعدة (لن تتغير) ──\n", "right")
        if self.excluded_names:
            for name in sorted(self.excluded_names, key=natural_sort_key):
                text.insert("end", f"{name}\n", "right")
        else:
            text.insert("end", "(لا توجد ملفات مستبعدة)\n", "right")

        if conflicts:
            text.insert("end", "\n⚠ تعارض: الأسماء الجديدة التالية تتطابق مع ملفات مستبعدة:\n", "right")
            for c in conflicts:
                text.insert("end", f"{c}\n", "right")
            text.insert("end", "\nيجب حل هذا التعارض قبل التنفيذ (مثلاً بإلغاء استبعاد الملف الذي يحمل هذا الاسم).\n", "right")

        text.config(state="disabled")
        ttk.Button(win, text="إغلاق", command=win.destroy).pack(pady=8)

    def confirm_and_rename(self):
        if not self.pdf_files:
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
                "تعذر إعادة التسمية بسبب تعارض الأسماء مع ملفات مستبعدة:\n"
                + "\n".join(conflicts)
                + "\n\nيرجى تعديل الاستبعادات أو نقل الملف المتعارض ثم المحاولة مرة أخرى."
            )
            return

        unchanged = sum(1 for old, new in mapping if old == new)
        will_change = len(mapping) - unchanged

        confirmed = messagebox.askyesno(
            APP_TITLE,
            f"سيتم إعادة تسمية {len(mapping)} ملف PDF بشكل تسلسلي (1.pdf, 2.pdf, ...).\n"
            f"عدد الملفات المستبعدة (لن تتغير): {len(self.excluded_names)}\n\n"
            "هل تريد المتابعة؟ هذا الإجراء لا يمكن التراجع عنه تلقائيًا."
        )
        if not confirmed:
            return

        self.rename_btn.config(state="disabled")
        self.status_var.set("جاري إعادة التسمية...")
        threading.Thread(target=self._rename_worker, args=(mapping,), daemon=True).start()

    def _rename_worker(self, mapping):
        """
        ينفذ إعادة التسمية فعليًا على القرص في خيط منفصل (لتجنب تجمد الواجهة).
        يستخدم إعادة تسمية بخطوتين (عبر اسم مؤقت فريد) لتجنب أي تعارض مؤقت
        بين الملفات التي يُعاد ترتيبها فيما بينها.
        """
        renamed_count = 0
        errors = []

        # الخطوة 1: إعادة تسمية كل ملف مستهدف إلى اسم مؤقت فريد لتجنّب التعارضات الوسيطة
        temp_map = []  # (temp_name, final_new_name, original_old_name)
        try:
            for old, new in mapping:
                if old == new:
                    # الاسم الجديد مطابق للاسم القديم، لا حاجة لإعادة التسمية
                    renamed_count += 1
                    continue
                old_path = os.path.join(self.folder, old)
                temp_name = f"~tmp_{uuid.uuid4().hex}.pdf"
                temp_path = os.path.join(self.folder, temp_name)
                os.rename(old_path, temp_path)
                temp_map.append((temp_path, new, old))

            # الخطوة 2: إعادة تسمية الأسماء المؤقتة إلى أسمائها النهائية
            for temp_path, new, old in temp_map:
                new_path = os.path.join(self.folder, new)
                os.rename(temp_path, new_path)
                renamed_count += 1
        except PermissionError as e:
            errors.append(f"خطأ في الأذونات: {e}")
        except FileNotFoundError as e:
            errors.append(f"ملف غير موجود: {e}")
        except OSError as e:
            errors.append(f"خطأ في نظام الملفات: {e}")
        except Exception as e:
            errors.append(f"خطأ غير متوقع: {e}")

        self.root.after(0, lambda: self._rename_done(renamed_count, errors))

    def _rename_done(self, renamed_count, errors):
        self.rename_btn.config(state="normal")

        if errors:
            messagebox.showerror(
                APP_TITLE,
                "حدثت أخطاء خلال إعادة التسمية:\n" + "\n".join(errors)
            )
            self.status_var.set("اكتملت العملية مع وجود أخطاء.")
        else:
            messagebox.showinfo(
                APP_TITLE,
                f"تمت العملية بنجاح ✅\n\n"
                f"عدد الملفات التي أُعيدت تسميتها: {renamed_count}\n"
                f"عدد الملفات المستبعدة (دون تغيير): {len(self.excluded_names)}"
            )
            self.status_var.set(
                f"تم! {renamed_count} ملف أُعيد تسميته، "
                f"{len(self.excluded_names)} ملف مستبعد."
            )

        # إعادة مسح المجلد لتحديث القائمة بالحالة الجديدة بعد إعادة التسمية
        self._scan_folder_async()


# --------------------------------------------------------------------------- #
# نقطة الدخول
# --------------------------------------------------------------------------- #

def main():
    root = tk.Tk()
    try:
        # تحسين بسيط للمظهر على الأنظمة التي تدعم الثيمات الحديثة
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        elif "clam" in style.theme_names():
            style.theme_use("clam")
    except Exception:
        pass

    app = PDFRenamerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
