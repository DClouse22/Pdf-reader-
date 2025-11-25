
import streamlit as st
import fitz
import re
import pandas as pd
from collections import defaultdict
from fpdf import FPDF
import io
import plotly.express as px

# ------------------- PAGE CONFIG -------------------
st.set_page_config(page_title="ILEARN Analytics Tool", layout="wide")

# ------------------- HEADER -------------------
st.title("📊 ILEARN Analytics Tool v3")
st.markdown("Enhanced PDF parsing with interactive charts and filters")

# ------------------- SIDEBAR -------------------
st.sidebar.header("Settings")
school_name = st.sidebar.text_input("Enter School Name (optional):", "")
logo_file = st.sidebar.file_uploader("Upload School Logo (optional):", type=["png", "jpg", "jpeg"])

# ------------------- FILE UPLOAD -------------------
uploaded_files = st.file_uploader("Drop ILEARN PDF reports here or click to browse", type="pdf", accept_multiple_files=True)

if not uploaded_files:
    st.warning("Please upload at least one PDF file to proceed.")
    st.stop()

# ------------------- DATA STRUCTURES -------------------
standards_items = defaultdict(set)
standards_counts = defaultdict(lambda: {"Full Credit": 0, "Partial Credit": 0, "No Credit": 0})
student_data = defaultdict(lambda: defaultdict(lambda: {"Full Credit": 0, "Partial Credit": 0, "No Credit": 0}))
student_names, lexile_values, proficiency_levels = [], [], []
standard_pattern = re.compile(r"RC\\n5\\.RC\\.\\d+")

# ------------------- PARSE PDFs -------------------
for uploaded_file in uploaded_files:
    try:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        current_student = None
        for page in doc:
            text = page.get_text()
            lines = text.split("\n")
            current_standard = None
            for line in lines:
                if line.startswith("Name:"):
                    current_student = line.replace("Name:", "").strip()
                    student_names.append(current_student)
                if "Lexile" in line:
                    lex_match = re.search(r"(\d+)L", line)
                    if lex_match:
                        lexile_values.append(int(lex_match.group(1)))
                if "Performance Level:" in line:
                    proficiency_levels.append(line.split(":")[-1].strip())
                match = standard_pattern.search(line)
                if match:
                    current_standard = match.group()
                    standards_items[current_standard].add(line.strip())
                if current_standard and current_student:
                    if "✓" in line or "v" in line:
                        standards_counts[current_standard]["Full Credit"] += 1
                        student_data[current_student][current_standard]["Full Credit"] += 1
                    elif "O" in line:
                        standards_counts[current_standard]["Partial Credit"] += 1
                        student_data[current_student][current_standard]["Partial Credit"] += 1
                    elif "X" in line:
                        standards_counts[current_standard]["No Credit"] += 1
                        student_data[current_student][current_standard]["No Credit"] += 1
    except Exception as e:
        st.error(f"Error processing {uploaded_file.name}: {e}")

# ------------------- DASHBOARD METRICS -------------------
total_students = len(set(student_names))
avg_lexile = int(sum(lexile_values) / len(lexile_values)) if lexile_values else 0
at_above = sum(1 for level in proficiency_levels if "At" in level or "Above" in level)
needs_support = total_students - at_above
at_above_pct = (at_above / total_students) * 100 if total_students else 0
needs_support_pct = (needs_support / total_students) * 100 if total_students else 0

st.subheader("📈 Dashboard Metrics")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Students", total_students)
col2.metric("At/Above Proficiency", f"{at_above_pct:.1f}%")
col3.metric("Needs Support", f"{needs_support_pct:.1f}%")
col4.metric("Average Lexile", f"{avg_lexile}L")

# ------------------- CLASS OVERVIEW -------------------
st.subheader("📚 Academic Standards Performance - Class Overview")
data = []
for standard in standards_items:
    unique_items = len(standards_items[standard])
    full_credit = standards_counts[standard]["Full Credit"]
    partial_credit = standards_counts[standard]["Partial Credit"]
    no_credit = standards_counts[standard]["No Credit"]
    success_rate = (full_credit / unique_items * 100) if unique_items > 0 else 0
    data.append([standard, total_students, unique_items, full_credit, partial_credit, no_credit, f"{success_rate:.0f}%"])

df = pd.DataFrame(data, columns=["Academic Standard", "Students", "Total Tests", "Full Credit (✓)", "Partial Credit (O)", "No Credit (X)", "Success Rate"])
st.dataframe(df)

# ------------------- INTERACTIVE CHART -------------------
fig = px.bar(df, x="Academic Standard", y=df["Success Rate"].str.replace("%", "").astype(float),
             title="Academic Standards Success Rate", labels={"y": "Success Rate (%)"}, color="Success Rate")
st.plotly_chart(fig, use_container_width=True)

# ------------------- FILTERS -------------------
st.subheader("🔍 Filters")
lexile_min, lexile_max = st.slider("Filter by Lexile Range", min_value=min(lexile_values) if lexile_values else 0,
                                   max_value=max(lexile_values) if lexile_values else 2000, value=(0, 2000))
filtered_students = [name for name in set(student_names) if any(lexile_min <= val <= lexile_max for val in lexile_values)]

# ------------------- PER-STUDENT BREAKDOWN -------------------
st.subheader("👩‍🎓 Academic Standards Performance - By Student")
for name in filtered_students:
    with st.expander(name):
        student_rows = []
        for standard, counts in student_data[name].items():
            total_tests = sum(counts.values())
            success_rate = (counts["Full Credit"] / total_tests * 100) if total_tests > 0 else 0
            student_rows.append([standard, total_tests, counts["Full Credit"], counts["Partial Credit"], counts["No Credit"], f"{success_rate:.0f}%"])
        student_df = pd.DataFrame(student_rows, columns=["Academic Standard", "Total Tests", "Full Credit (✓)", "Partial Credit (O)", "No Credit (X)", "Success Rate"])
        st.table(student_df)

# ------------------- DOWNLOAD OPTIONS -------------------
csv = df.to_csv(index=False).encode("utf-8")
st.download_button("Download Class Overview as CSV", csv, "class_overview.csv", "text/csv")

# ------------------- PDF EXPORT -------------------
def create_pdf():
    pdf = FPDF()
    pdf.add_page()
    if logo_file:
        img_buffer = io.BytesIO(logo_file.read())
        pdf.image(img_buffer, x=10, y=8, w=30)
    pdf.set_font("Arial", "B", 16)
    pdf.cell(0, 10, "ILEARN Analytics Report", ln=True, align="C")
    if school_name:
        pdf.set_font("Arial", "I", 14)
        pdf.cell(0, 10, school_name, ln=True, align="C")
    pdf.set_font("Arial", "", 12)
    pdf.cell(0, 10, f"Generated on: {pd.Timestamp.now().strftime('%Y-%m-%d')}", ln=True)
    pdf.ln(10)
    pdf.set_font("Arial", "B", 12)
    pdf.cell(0, 10, "Class Overview", ln=True)
    pdf.set_font("Arial", "", 10)
    for i, row in df.iterrows():
        pdf.cell(0, 8, f"{row['Academic Standard']} | Success: {row['Success Rate']}", ln=True)
    return pdf.output(dest="S").encode("latin-1")

pdf_bytes = create_pdf()
st.download_button("Download Full Report as PDF", pdf_bytes, "ILEARN_Analytics_Report.pdf", "application/pdf")

