# School Payroll – Local Flask Version

This is the first local version of the school payroll application.

## 1. Install Python

Install Python 3.11 or newer on Windows. During installation, tick:

    Add Python to PATH

## 2. Open Command Prompt

Go to this folder:

    cd SchoolPayroll

## 3. Create a virtual environment

    py -m venv .venv

Activate it:

    .venv\Scripts\activate

## 4. Install Flask

    pip install -r requirements.txt

## 5. Start the application

    py app.py

Then open Chrome:

    http://127.0.0.1:5000

## 6. Import the SAP files

Use the Import SAP Data page and upload:

- ZSKV_EMPMASTER.xls
- ZSKV_EMPSALARY.xls

These files are SAP Dynamic List Display exports encoded as UTF-16 tab-delimited text.

## 7. Payroll workflow

1. Import employee master.
2. Import salary master.
3. Select payroll month/year.
4. The system lists eligible employees.
5. Enter leave deduction days.
6. Calculate payroll.
7. Review the salary result.
8. Save the payroll run.

## SAP calculation implemented

The calculation follows the supplied ZSKV_SALARY_GENERATION program:

- Employee eligibility based on joining/resignation dates.
- Mid-month joining proration for Basic, DA, HRA, Conveyance and Special Allowance.
- Leave deduction based on the sum of those salary components.
- Gross salary after leave deduction.
- PF: employee 12%, employer PF equal to employee PF, employer admin 1%.
- ESI: employee 0.75%, employer 3.25%.
- Total deduction = employee PF + employee ESI.
- Net salary = gross salary - total deduction.
- Total CTC = gross salary + employer PF + employer ESI + employer admin.

### Important source-code detail

The supplied ABAP program selects the salary record using the current SAP date (`SY-DATUM`) for the validity check, rather than the selected payroll month. This first Flask version mirrors that behavior exactly. We can change this later if your intended rule is to select the salary record applicable to the payroll month.

## Current scope

This is Version 1. It intentionally focuses on the core payroll workflow. The saved payroll can now be downloaded as an Excel salary file with the requested columns and a TOTAL row at the bottom. Payslip PDF, authentication, audit controls, backups, and Google Cloud deployment can be added after the calculation is verified against SAP output.


## Payroll History / Excel
Each saved payroll run in Payroll History now has:
- View
- Download Excel

The saved payroll screen also shows a SUBTOTAL row at the bottom, and the downloaded Excel file includes the same SUBTOTAL row.
# Skvapp
