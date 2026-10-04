from flask import Flask, render_template, request, redirect, url_for, flash, send_file
import sqlite3
from pathlib import Path
from datetime import datetime, date
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN, ROUND_HALF_UP, ROUND_FLOOR
import csv
import io
import math

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "payroll.db"

app = Flask(__name__)
app.secret_key = "change-this-secret-key"

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS employees (
        empno TEXT PRIMARY KEY,
        emp_type TEXT,
        first_name TEXT,
        last_name TEXT,
        full_name TEXT,
        designation TEXT,
        dob TEXT,
        gender TEXT,
        qualification TEXT,
        pre_exp TEXT,
        telephone1 TEXT,
        telephone2 TEXT,
        job_profile TEXT,
        joining_date TEXT NOT NULL,
        email TEXT,
        street TEXT,
        street2 TEXT,
        street3 TEXT,
        city TEXT,
        state TEXT,
        ctr TEXT,
        postal_code TEXT,
        doc_sub TEXT,
        resig_date TEXT,
        resig_reason TEXT,
        aadhar_no TEXT,
        pan_no TEXT,
        bank_ac TEXT,
        bank_name TEXT,
        prev_esi TEXT,
        prev_pf TEXT,
        curr_esi TEXT,
        current_pf TEXT,
        age TEXT,
        community TEXT,
        religion TEXT,
        caste TEXT,
        marital_status TEXT,
        pf_applicable INTEGER DEFAULT 0,
        esi_applicable INTEGER DEFAULT 0,
        created_by TEXT,
        created_on TEXT
    );

    CREATE TABLE IF NOT EXISTS salaries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        empno TEXT NOT NULL,
        valid_from TEXT NOT NULL,
        valid_to TEXT NOT NULL,
        basic REAL DEFAULT 0,
        da REAL DEFAULT 0,
        hra REAL DEFAULT 0,
        conveyance REAL DEFAULT 0,
        special_allowance REAL DEFAULT 0,
        FOREIGN KEY(empno) REFERENCES employees(empno)
    );

    CREATE TABLE IF NOT EXISTS leave_deductions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        empno TEXT NOT NULL,
        payroll_month INTEGER NOT NULL,
        payroll_year INTEGER NOT NULL,
        leave_days REAL NOT NULL DEFAULT 0,
        UNIQUE(empno, payroll_month, payroll_year)
    );

    CREATE TABLE IF NOT EXISTS payroll_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payroll_month INTEGER NOT NULL,
        payroll_year INTEGER NOT NULL,
        created_on TEXT NOT NULL,
        created_by TEXT,
        UNIQUE(payroll_month, payroll_year)
    );

    CREATE TABLE IF NOT EXISTS payroll_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id INTEGER NOT NULL,
        empno TEXT NOT NULL,
        full_name TEXT,
        joining_date TEXT,
        leave_days REAL,
        basic REAL,
        da REAL,
        hra REAL,
        conveyance REAL,
        special_allowance REAL,
        leave_deduct REAL,
        gross_salary REAL,
        employee_pf REAL,
        employer_pf REAL,
        employer_admin REAL,
        employee_esi REAL,
        employer_esi REAL,
        total_deduct REAL,
        net_salary REAL,
        total_ctc REAL,
        FOREIGN KEY(run_id) REFERENCES payroll_runs(id)
    );
    """)
    conn.commit()
    conn.close()

def parse_date(s):
    if s is None:
        return None
    s = str(s).strip()
    if not s or s in ("0", "00.00.0000"):
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None

def iso(d):
    return d.isoformat() if d else None

def money(v):
    return Decimal(str(v or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def sap_ceil(v):
    # School payroll rounding rule:
    # decimal part < 0.50  -> floor
    # decimal part >= 0.50 -> ceil
    v = Decimal(v)
    whole = v.to_integral_value(rounding=ROUND_FLOOR)
    decimal_part = v - whole
    if decimal_part < Decimal("0.50"):
        return whole
    return whole + Decimal("1")

def sap_trunc_half(v):
    # PF/admin contribution rounding: nearest whole rupee.
    # For positive values, .50 and above rounds up; below .50 rounds down.
    v = Decimal(v)
    whole = v.to_integral_value(rounding=ROUND_FLOOR)
    decimal_part = v - whole
    if decimal_part < Decimal("0.50"):
        return whole
    return whole + Decimal("1")

def pf_round(v):
    # PF is calculated using normal nearest-rupee rounding.
    return sap_trunc_half(v)

def esi_ceil(v):
    # ESI is always rounded upward to the next whole rupee.
    v = Decimal(v)
    return v.to_integral_value(rounding=ROUND_CEILING)

def number(v):
    if v is None:
        return Decimal("0")
    s = str(v).strip().replace(",", "")
    if not s:
        return Decimal("0")
    try:
        return Decimal(s)
    except Exception:
        return Decimal("0")

def parse_sap_dynamic_file(file_bytes):
    text = file_bytes.decode("utf-16")
    lines = text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if "Emp No" in line:
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("Could not find the SAP header row.")
    rows = []
    reader = csv.reader(io.StringIO("\n".join(lines[header_idx:])), delimiter="\t")
    for row in reader:
        if not row or not any(str(x).strip() for x in row):
            continue
        # SAP exports have a leading empty column.
        if row and not str(row[0]).strip() and len(row) > 1:
            row = row[1:]
        rows.append([str(x).strip() for x in row])
    headers = rows[0]
    data = []
    for row in rows[1:]:
        row = row + [""] * max(0, len(headers)-len(row))
        data.append(dict(zip(headers, row[:len(headers)])))
    return data

def import_employees(file_bytes):
    rows = parse_sap_dynamic_file(file_bytes)
    conn = db()
    count = 0
    for r in rows:
        empno = r.get("Emp No", "").strip()
        if not empno:
            continue
        vals = (
            empno, r.get("Emp.type",""), r.get("First name",""), r.get("Last name",""),
            r.get("Full Name",""), r.get("Designation",""), r.get("DOB",""),
            r.get("Gender",""), r.get("Qualif.",""), r.get("Pre.Exp.",""),
            r.get("Telephone1",""), r.get("Telephone2",""), r.get("Job Profile",""),
            iso(parse_date(r.get("Join.Date"))), r.get("E-Mail",""),
            r.get("Street",""), r.get("Street 2",""), r.get("Street 3",""),
            r.get("City",""), r.get("State",""), r.get("Ctr",""), r.get("Postl Code",""),
            r.get("Doc.Sub",""), iso(parse_date(r.get("Resig.Date"))),
            r.get("Resig.Reas",""), r.get("Aadhar No.",""), r.get("Pan No",""),
            r.get("Bank A/c",""), r.get("Bank Name",""), r.get("Prev.ESI",""),
            r.get("Prev.PF",""), r.get("Curr.ESI",""), r.get("Current PF",""),
            r.get("Age",""), r.get("Community",""), r.get("Religion",""),
            r.get("Caste",""), r.get("Maritial Status",""),
            1 if r.get("Pf appl.","").strip().upper() == "X" else 0,
            1 if r.get("Esi App.","").strip().upper() == "X" else 0,
            r.get("Created by",""), r.get("Created on","")
        )
        conn.execute("""
        INSERT INTO employees (
          empno,emp_type,first_name,last_name,full_name,designation,dob,gender,
          qualification,pre_exp,telephone1,telephone2,job_profile,joining_date,
          email,street,street2,street3,city,state,ctr,postal_code,doc_sub,
          resig_date,resig_reason,aadhar_no,pan_no,bank_ac,bank_name,prev_esi,
          prev_pf,curr_esi,current_pf,age,community,religion,caste,marital_status,
          pf_applicable,esi_applicable,created_by,created_on
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(empno) DO UPDATE SET
          emp_type=excluded.emp_type, first_name=excluded.first_name,
          last_name=excluded.last_name, full_name=excluded.full_name,
          designation=excluded.designation, joining_date=excluded.joining_date,
          resig_date=excluded.resig_date, pf_applicable=excluded.pf_applicable,
          esi_applicable=excluded.esi_applicable
        """, vals)
        count += 1
    conn.commit()
    conn.close()
    return count

def import_salaries(file_bytes):
    rows = parse_sap_dynamic_file(file_bytes)
    conn = db()
    count = 0
    for r in rows:
        empno = r.get("Emp No", "").strip()
        if not empno:
            continue
        conn.execute("""
          INSERT INTO salaries
          (empno,valid_from,valid_to,basic,da,hra,conveyance,special_allowance)
          VALUES (?,?,?,?,?,?,?,?)
        """, (
            empno,
            iso(parse_date(r.get("Valid From"))),
            iso(parse_date(r.get("Valid To"))),
            float(number(r.get("Basic"))), float(number(r.get("DA"))),
            float(number(r.get("HRA"))), float(number(r.get("Conveyance"))),
            float(number(r.get("Sp.Allowan")))
        ))
        count += 1
    conn.commit()
    conn.close()
    return count

def month_bounds(year, month):
    start = date(year, month, 1)
    if month == 12:
        end = date(year, 12, 31)
    else:
        end = date(year, month+1, 1).replace(day=1)
        end = end.fromordinal(end.toordinal()-1)
    return start, end

def eligible_employees(year, month):
    start, end = month_bounds(year, month)
    conn = db()
    rows = conn.execute("""
      SELECT * FROM employees
      WHERE (resig_date IS NULL OR resig_date > ?)
        AND joining_date < ?
      ORDER BY empno
    """, (iso(start), iso(end))).fetchall()
    conn.close()
    return rows

def salary_for_employee(empno, year, month):
    # Select the salary record applicable to the selected payroll month.
    start, end = month_bounds(year, month)
    conn = db()
    row = conn.execute("""
      SELECT * FROM salaries
      WHERE empno=?
        AND valid_from <= ?
        AND valid_to >= ?
      ORDER BY valid_from DESC
      LIMIT 1
    """, (empno, iso(end), iso(start))).fetchone()
    conn.close()
    return row

def get_leave(empno, month, year):
    conn = db()
    row = conn.execute("""
      SELECT leave_days FROM leave_deductions
      WHERE empno=? AND payroll_month=? AND payroll_year=?
    """, (empno, month, year)).fetchone()
    conn.close()
    return float(row["leave_days"]) if row else 0.0

def calculate_employee(emp, salary, leave_days, year, month):
    # The same payroll rounding rule applies to all five salary components
    # when monthly proration is required:
    # Basic Salary, DA, HRA, Special Allowance and Conveyance.
    start, end = month_bounds(year, month)
    days = Decimal(end.day)

    basic = number(salary["basic"])
    da = number(salary["da"])
    hra = number(salary["hra"])
    conveyance = number(salary["conveyance"])
    special = number(salary["special_allowance"])

    joining = parse_date(emp["joining_date"])
    if joining and joining > start:
        days1 = Decimal((end - joining).days + 1)
        basic = sap_ceil((basic / days) * days1)
        da = sap_ceil((da / days) * days1)
        hra = sap_ceil((hra / days) * days1)
        conveyance = sap_ceil((conveyance / days) * days1)
        special = sap_ceil((special / days) * days1)

    leave_calc = basic + da + hra + conveyance + special
    leave_deduct = Decimal("0")
    if leave_days:
        leave_deduct = sap_trunc_half((leave_calc / days) * Decimal(str(leave_days)))

    gross = leave_calc - leave_deduct

    employee_pf = employer_pf = employer_admin = Decimal("0")
    if emp["pf_applicable"]:
        pf_calc = basic + da
        basda = pf_calc - ((pf_calc / days) * Decimal(str(leave_days)))
        employee_pf = pf_round(basda * Decimal("0.12"))
        employer_pf = employee_pf
        employer_admin = pf_round(basda * Decimal("0.01"))

    employee_esi = employer_esi = Decimal("0")
    if emp["esi_applicable"]:
        employee_esi = esi_ceil(gross * Decimal("0.0075"))
        employer_esi = esi_ceil(gross * Decimal("0.0325"))

    total_deduct = employee_pf + employee_esi
    net = gross - total_deduct
    total_ctc = gross + employer_pf + employer_esi + employer_admin

    return {
        "empno": emp["empno"], "full_name": emp["full_name"],
        "joining_date": emp["joining_date"], "leave_days": float(leave_days),
        "basic": float(basic), "da": float(da), "hra": float(hra),
        "conveyance": float(conveyance), "special_allowance": float(special),
        "leave_deduct": float(leave_deduct), "gross_salary": float(gross),
        "employee_pf": float(employee_pf), "employer_pf": float(employer_pf),
        "employer_admin": float(employer_admin), "employee_esi": float(employee_esi),
        "employer_esi": float(employer_esi), "total_deduct": float(total_deduct),
        "net_salary": float(net), "total_ctc": float(total_ctc)
    }

@app.route("/")
def index():
    conn = db()
    employees = conn.execute("SELECT COUNT(*) c FROM employees").fetchone()["c"]
    salaries = conn.execute("SELECT COUNT(*) c FROM salaries").fetchone()["c"]
    runs = conn.execute("SELECT COUNT(*) c FROM payroll_runs").fetchone()["c"]
    conn.close()
    return render_template("index.html", employees=employees, salaries=salaries, runs=runs)

@app.route("/employees")
def employees():
    conn = db()
    rows = conn.execute("SELECT * FROM employees ORDER BY empno").fetchall()
    conn.close()
    return render_template("employees.html", employees=rows)

@app.route("/salary-master")
def salary_master():
    conn = db()
    rows = conn.execute("""
      SELECT s.*, e.full_name FROM salaries s
      LEFT JOIN employees e ON e.empno=s.empno
      ORDER BY s.empno, s.valid_from DESC
    """).fetchall()
    conn.close()
    return render_template("salary_master.html", salaries=rows)

@app.route("/import", methods=["GET","POST"])
def import_page():
    if request.method == "POST":
        emp_file = request.files.get("employee_file")
        sal_file = request.files.get("salary_file")
        try:
            if emp_file and emp_file.filename:
                n = import_employees(emp_file.read())
                flash(f"Employee master imported: {n} records.", "success")
            if sal_file and sal_file.filename:
                n = import_salaries(sal_file.read())
                flash(f"Salary master imported: {n} records.", "success")
        except Exception as e:
            flash(f"Import failed: {e}", "error")
        return redirect(url_for("import_page"))
    return render_template("import.html")

@app.route("/payroll", methods=["GET","POST"])
def payroll():
    if request.method == "POST":
        month = int(request.form["month"])
        year = int(request.form["year"])
        emps = eligible_employees(year, month)
        for emp in emps:
            leave = float(request.form.get(f"leave_{emp['empno']}", "0") or 0)
            conn = db()
            conn.execute("""
              INSERT INTO leave_deductions(empno,payroll_month,payroll_year,leave_days)
              VALUES (?,?,?,?)
              ON CONFLICT(empno,payroll_month,payroll_year)
              DO UPDATE SET leave_days=excluded.leave_days
            """, (emp["empno"], month, year, leave))
            conn.commit()
            conn.close()
        return redirect(url_for("payroll_preview", month=month, year=year))

    now = date.today()
    month = int(request.args.get("month", now.month))
    year = int(request.args.get("year", now.year))
    emps = eligible_employees(year, month)

    # Load saved leave deductions for the selected month/year.
    conn = db()
    saved_leave_rows = conn.execute("""
        SELECT empno, leave_days
        FROM leave_deductions
        WHERE payroll_month=? AND payroll_year=?
    """, (month, year)).fetchall()
    conn.close()

    leave_values = {
        row["empno"]: row["leave_days"]
        for row in saved_leave_rows
    }

    return render_template(
        "payroll.html",
        employees=emps,
        month=month,
        year=year,
        leave_values=leave_values
    )

@app.route("/payroll/preview")
def payroll_preview():
    month = int(request.args["month"])
    year = int(request.args["year"])
    emps = eligible_employees(year, month)
    results, missing = [], []
    for emp in emps:
        sal = salary_for_employee(emp["empno"], year, month)
        if not sal:
            missing.append(emp["empno"])
            continue
        results.append(calculate_employee(emp, sal, get_leave(emp["empno"], month, year), year, month))
    return render_template("payroll_preview.html", results=results, missing=missing, month=month, year=year)

@app.route("/payroll/save", methods=["POST"])
def payroll_save():
    month = int(request.form["month"])
    year = int(request.form["year"])
    emps = eligible_employees(year, month)
    conn = db()
    now = datetime.now().isoformat(timespec="seconds")
    try:
        cur = conn.execute("""
          INSERT INTO payroll_runs(payroll_month,payroll_year,created_on,created_by)
          VALUES (?,?,?,?)
          ON CONFLICT(payroll_month,payroll_year)
          DO UPDATE SET created_on=excluded.created_on, created_by=excluded.created_by
        """, (month, year, now, "LOCAL_ADMIN"))
        run = conn.execute("SELECT id FROM payroll_runs WHERE payroll_month=? AND payroll_year=?", (month, year)).fetchone()
        run_id = run["id"]
        conn.execute("DELETE FROM payroll_results WHERE run_id=?", (run_id,))
        for emp in emps:
            sal = salary_for_employee(emp["empno"], year, month)
            if not sal:
                continue
            r = calculate_employee(emp, sal, get_leave(emp["empno"], month, year), year, month)
            conn.execute("""
            INSERT INTO payroll_results
            (run_id,empno,full_name,joining_date,leave_days,basic,da,hra,conveyance,
             special_allowance,leave_deduct,gross_salary,employee_pf,employer_pf,
             employer_admin,employee_esi,employer_esi,total_deduct,net_salary,total_ctc)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (run_id,r["empno"],r["full_name"],r["joining_date"],r["leave_days"],
                  r["basic"],r["da"],r["hra"],r["conveyance"],r["special_allowance"],
                  r["leave_deduct"],r["gross_salary"],r["employee_pf"],r["employer_pf"],
                  r["employer_admin"],r["employee_esi"],r["employer_esi"],
                  r["total_deduct"],r["net_salary"],r["total_ctc"]))
        conn.commit()
        flash("Payroll saved successfully.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Could not save payroll: {e}", "error")
    finally:
        conn.close()
    return redirect(url_for("payroll_history"))
@app.route("/payroll/export/<int:run_id>")
def payroll_export(run_id):
    from flask import send_file
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    import io

    conn = db()

    run = conn.execute(
        "SELECT * FROM payroll_runs WHERE id=?",
        (run_id,)
    ).fetchone()

    rows = conn.execute(
        "SELECT * FROM payroll_results WHERE run_id=? ORDER BY empno",
        (run_id,)
    ).fetchall()

    employees = conn.execute(
        "SELECT empno, designation FROM employees"
    ).fetchall()

    designation_map = {
        row["empno"]: row["designation"] or ""
        for row in employees
    }

    conn.close()

    if not run:
        flash("Payroll run not found.", "error")
        return redirect(url_for("payroll_history"))

    wb = Workbook()
    ws = wb.active
    ws.title = f"{int(run['payroll_month']):02d}-{run['payroll_year']}"

    headers = [
        "Designation",
        "Employee ID",
        "Employee Name",
        "Basic Salary",
        "DA",
        "HRA(+)",
        "Special Allowance(+)",
        "Conveyance(+)",
        "Leave Days",
        "Gross",
        "PF",
        "ESI",
        "Total Deduction",
        "Net Salary",
        "Month",
        "No. of Days"
    ]

    ws.append(headers)

    for r in rows:
        month = int(run["payroll_month"])
        year = int(run["payroll_year"])

        if month == 2:
            no_of_days = 29 if year % 4 == 0 else 28
        elif month in (4, 6, 9, 11):
            no_of_days = 30
        else:
            no_of_days = 31

        ws.append([
            designation_map.get(r["empno"], ""),
            r["empno"],
            r["full_name"] or "",
            r["basic"],
            r["da"],
            r["hra"],
            r["special_allowance"],
            r["conveyance"],
            r["leave_days"],
            r["gross_salary"],
            r["employee_pf"],
            r["employee_esi"],
            r["total_deduct"],
            r["net_salary"],
            f"{month:02d}/{year}",
            no_of_days
        ])

    # SUBTOTAL ROW
    subtotal_row = ws.max_row + 1

    ws.cell(subtotal_row, 1, "SUBTOTAL")

    for col in range(4, 15):
        letter = get_column_letter(col)
        ws.cell(
            subtotal_row,
            col,
            f"=SUM({letter}2:{letter}{subtotal_row - 1})"
        )

    # Formatting
    header_fill = PatternFill(
        "solid",
        fgColor="D9EAF7"
    )

    subtotal_fill = PatternFill(
        "solid",
        fgColor="FFF2CC"
    )

    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(
            horizontal="center",
            vertical="center",
            wrap_text=True
        )

    for cell in ws[subtotal_row]:
        cell.font = Font(bold=True)
        cell.fill = subtotal_fill

    # Number formatting
    for row in ws.iter_rows(
        min_row=2,
        max_row=subtotal_row,
        min_col=4,
        max_col=14
    ):
        for cell in row:
            cell.number_format = '#,##0.00'

    widths = [
        22, 16, 28, 15, 12, 12, 22, 17,
        12, 14, 12, 12, 18, 15, 14, 14
    ]

    for i, width in enumerate(widths, 1):
        ws.column_dimensions[
            get_column_letter(i)
        ].width = width

    ws.freeze_panes = "A2"

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename = (
        f"Salary_{int(run['payroll_month']):02d}_"
        f"{run['payroll_year']}.xlsx"
    )

    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype=(
            "application/vnd.openxmlformats-"
            "officedocument.spreadsheetml.sheet"
        )
    )

def _payslip_number(value):
    """Format a salary value as a whole-rupee amount for the payslip."""
    return f"{float(value or 0):.0f}"


def _build_payslip_pdf(rows, run):
    """
    Build a combined PDF with one payslip per employee, following the
    supplied school payslip layout.
    """
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        Image as RLImage, PageBreak, KeepTogether
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18*mm,
        leftMargin=18*mm,
        topMargin=0*mm,
        bottomMargin=12*mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "PayslipTitle", parent=styles["Title"],
        fontName="Times-Bold", fontSize=17, leading=20,
        alignment=TA_CENTER, spaceAfter=8
    )
    school_style = ParagraphStyle(
        "SchoolName", parent=styles["Normal"],
        fontName="Helvetica-Bold", fontSize=14, leading=16,
        textColor=colors.HexColor("#183b78"), alignment=TA_CENTER
    )
    sub_school_style = ParagraphStyle(
        "SchoolSub", parent=styles["Normal"],
        fontName="Helvetica-Bold", fontSize=9.5, leading=11,
        textColor=colors.HexColor("#1f6b45"), alignment=TA_CENTER
    )
    small_center = ParagraphStyle(
        "SmallCenter", parent=styles["Normal"],
        fontName="Times-Roman", fontSize=8.5, leading=10,
        alignment=TA_CENTER
    )
    label_style = ParagraphStyle(
        "Label", parent=styles["Normal"],
        fontName="Times-Roman", fontSize=10.5, leading=13
    )
    value_style = ParagraphStyle(
        "Value", parent=styles["Normal"],
        fontName="Times-Roman", fontSize=10.5, leading=13
    )
    bold_value = ParagraphStyle(
        "BoldValue", parent=value_style, fontName="Times-Bold"
    )
    money_style = ParagraphStyle(
        "Money", parent=value_style, alignment=TA_RIGHT
    )
    bold_money = ParagraphStyle(
        "BoldMoney", parent=money_style, fontName="Times-Bold"
    )
    table_head = ParagraphStyle(
        "TableHead", parent=styles["Normal"],
        fontName="Times-Bold", fontSize=10.5, leading=12,
        alignment=TA_CENTER
    )
    table_cell = ParagraphStyle(
        "TableCell", parent=styles["Normal"],
        fontName="Times-Roman", fontSize=10.5, leading=12
    )
    table_money = ParagraphStyle(
        "TableMoney", parent=table_cell, alignment=TA_RIGHT
    )
    table_bold = ParagraphStyle(
        "TableBold", parent=table_cell, fontName="Times-Bold"
    )
    table_bold_money = ParagraphStyle(
        "TableBoldMoney", parent=table_money, fontName="Times-Bold"
    )

    logo_path = BASE_DIR / "static" / "school_logo.png"
    story = []

    month = int(run["payroll_month"])
    year = int(run["payroll_year"])
    month_name = date(year, month, 1).strftime("%B %Y")
    _, month_end = month_bounds(year, month)
    no_of_days = month_end.day

    for index, r in enumerate(rows):
        conn = db()
        emp = conn.execute(
            "SELECT designation FROM employees WHERE empno=?",
            (r["empno"],)
        ).fetchone()
        conn.close()
        designation = emp["designation"] if emp else ""

        # Use the supplied school header image. The image is kept intact and
        # only scaled proportionately to the payslip width.
        header_path = BASE_DIR / "static" / "payslip_header.png"
        header_width = 162 * mm
        header_height = header_width * 300 / 1094

        if header_path.exists():
            header_image = RLImage(
                str(header_path),
                width=header_width,
                height=header_height
            )
        else:
            header_image = Paragraph(
                "SHRI KHONGURUNATHAR VIDYALAYAM",
                school_style
            )

        header = Table(
            [[header_image]],
            colWidths=[header_width]
        )
        header.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "TOP"),
            ("LEFTPADDING", (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 0),
            ("TOPPADDING", (0,0), (-1,-1), 0),
            ("BOTTOMPADDING", (0,0), (-1,-1), 0),
        ]))
        story.append(header)
        story.append(Paragraph("PAYSLIP", title_style))

        # Employee details block
        info = [
            [Paragraph("Employee Name", label_style),
             Paragraph(r["full_name"] or "", bold_value),
             Paragraph("No. of Days in a Month", label_style),
             Paragraph(str(no_of_days), value_style)],
            [Paragraph("Designation", label_style),
             Paragraph(designation or "", value_style),
             Paragraph("Leave Days", label_style),
             Paragraph(f"{float(r['leave_days'] or 0):g}", value_style)],
            [Paragraph("Pay Period", label_style),
             Paragraph(month_name, value_style),
             "", ""],
        ]
        info_table = Table(info, colWidths=[42*mm, 48*mm, 55*mm, 17*mm])
        info_table.setStyle(TableStyle([
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("LEFTPADDING", (0,0), (-1,-1), 0),
            ("RIGHTPADDING", (0,0), (-1,-1), 0),
            ("TOPPADDING", (0,0), (-1,-1), 1.5*mm),
            ("BOTTOMPADDING", (0,0), (-1,-1), 1.5*mm),
        ]))
        story.append(info_table)
        story.append(Spacer(1, 5*mm))

        # Total Deduction = PF + ESI + Leave Deduction.
        payslip_total_deduction = (
            Decimal(str(r["employee_pf"] or 0))
            + Decimal(str(r["employee_esi"] or 0))
            + Decimal(str(r["leave_deduct"] or 0))
        )

        earnings = [
            [Paragraph("Earnings", table_head), Paragraph("Amount", table_head),
             Paragraph("Deductions", table_head), Paragraph("Amount", table_head)],
            [Paragraph("Basic Salary", table_cell), Paragraph(_payslip_number(r["basic"]), table_money),
             Paragraph("PF", table_cell), Paragraph(_payslip_number(r["employee_pf"]), table_money)],
            [Paragraph("Dearness Allowance", table_cell), Paragraph(_payslip_number(r["da"]), table_money),
             Paragraph("ESI", table_cell), Paragraph(_payslip_number(r["employee_esi"]), table_money)],
            [Paragraph("House Rent Allowance", table_cell), Paragraph(_payslip_number(r["hra"]), table_money),
             Paragraph("Leave Deduction", table_cell), Paragraph(_payslip_number(r["leave_deduct"]), table_money)],
            [Paragraph("Special Allowance", table_cell), Paragraph(_payslip_number(r["special_allowance"]), table_money),
             "", ""],
            [Paragraph("Conveyance", table_cell), Paragraph(_payslip_number(r["conveyance"]), table_money),
             "", ""],
            [Paragraph("Total", table_bold), Paragraph(_payslip_number(r["gross_salary"]), table_bold_money),
             Paragraph("Total Deduction", table_bold), Paragraph(_payslip_number(payslip_total_deduction), table_bold_money)],
            ["", "", Paragraph("Net Salary", table_bold), Paragraph(_payslip_number(r["net_salary"]), ParagraphStyle(
                "NetMoney", parent=table_bold_money, fontSize=16, leading=17
            ))],
        ]

        payslip_table = Table(
            earnings,
            colWidths=[52*mm, 42*mm, 48*mm, 20*mm],
            rowHeights=[8*mm, 7.5*mm, 7.5*mm, 7.5*mm, 7.5*mm, 7.5*mm, 7.5*mm, 9*mm]
        )
        payslip_table.setStyle(TableStyle([
            ("GRID", (0,0), (-1,-1), 0.5, colors.black),
            ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
            ("LEFTPADDING", (0,0), (-1,-1), 2*mm),
            ("RIGHTPADDING", (0,0), (-1,-1), 2*mm),
            ("TOPPADDING", (0,0), (-1,-1), 0.5*mm),
            ("BOTTOMPADDING", (0,0), (-1,-1), 0.5*mm),
        ]))
        story.append(payslip_table)

        if index < len(rows) - 1:
            story.append(PageBreak())

    doc.build(story)
    buffer.seek(0)
    return buffer


@app.route("/payroll/payslips/<int:run_id>")
def payroll_payslips(run_id):
    conn = db()
    run = conn.execute(
        "SELECT * FROM payroll_runs WHERE id=?", (run_id,)
    ).fetchone()
    rows = conn.execute(
        "SELECT * FROM payroll_results WHERE run_id=? ORDER BY empno",
        (run_id,)
    ).fetchall()
    conn.close()

    if not run:
        flash("Payroll run not found.", "error")
        return redirect(url_for("payroll_history"))

    pdf = _build_payslip_pdf(rows, run)
    filename = f"Payslips_{int(run['payroll_month']):02d}_{run['payroll_year']}.pdf"
    return send_file(
        pdf,
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf"
    )


@app.route("/payroll/payslip/<int:run_id>/<empno>")
def payroll_payslip(run_id, empno):
    conn = db()
    run = conn.execute(
        "SELECT * FROM payroll_runs WHERE id=?", (run_id,)
    ).fetchone()
    row = conn.execute(
        "SELECT * FROM payroll_results WHERE run_id=? AND empno=?",
        (run_id, empno)
    ).fetchone()
    conn.close()

    if not run or not row:
        flash("Payslip not found.", "error")
        return redirect(url_for("payroll_history"))

    pdf = _build_payslip_pdf([row], run)
    filename = f"Payslip_{empno}_{int(run['payroll_month']):02d}_{run['payroll_year']}.pdf"
    return send_file(
        pdf,
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf"
    )

@app.route("/payroll/history")
def payroll_history():
    conn = db()
    runs = conn.execute("""
      SELECT * FROM payroll_runs ORDER BY payroll_year DESC, payroll_month DESC
    """).fetchall()
    conn.close()
    return render_template("history.html", runs=runs)

@app.route("/payroll/run/<int:run_id>")
def payroll_run(run_id):
    conn = db()
    run = conn.execute("SELECT * FROM payroll_runs WHERE id=?", (run_id,)).fetchone()
    rows = conn.execute("SELECT * FROM payroll_results WHERE run_id=? ORDER BY empno", (run_id,)).fetchall()
    conn.close()
    return render_template("run.html", run=run, results=rows)

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=8080, debug=True)
