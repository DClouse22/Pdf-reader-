
import streamlit as st
import fitz
import re
import pandas as pd
from collections import defaultdict
from fpdf import FPDF
import matplotlib.pyplot as plt
import io

# Custom CSS for styling
st.markdown("""
<style>
    .main-title {font-size: 32px; font-weight: bold; color: #4B4BFF; text-align: center;}
    .sub-title {font-size: 18px; color: #666; text-align: center; margin-bottom: 20px;}
    .metric-card {display: flex; justify-content: space-around; margin: 20px 0;}
    .metric-card div {background: #f8f9fa; padding: 20px; border-radius: 10px; text-align: center; width: 22%; box-shadow: 0 2px 5px rgba(0,0,0,0.1);}
    .metric-card h3 {margin: 0; font-size: 24px; color: #333;}
    .metric-card p {margin: 5px 0 0; font-size: 14px; color: #666;}
    .legend {margin-top: 10px; font-size: 14px; color: #555;}
</style>
""", unsafe_allow_html=True)

# Header
st.markdown('<div class="main-title">ILEARN Analytics Tool v2</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-title">Enhanced PDF parsing for accurate student name extraction</div>', unsafe_allow_html=True)

# School name and logo customization
school_name = st.text_input("Enter School Name (optional):", "")
logo_file = st.file_uploader("Upload School Logo (optional):", type=["png", "jpg", "jpeg"])
if logo_file:
    st.image(logo_file, width=120)
if school_name:
    st.markdown(f'<div style="text-align:center; font-size:20px; color:#333;">{school_name}</div>', unsafe_allow_html=True)

uploaded_files = st.file_uploader("Drop ILEARN PDF reports here or click to browse", type="pdf", accept_multiple_files=True)

if uploaded_files:
    st.progress(100)
    st.success("Processing complete! Parsing student data...")

    # Data structures
    standards_items = defaultdict(set)
    standards_counts = defaultdict(lambda: {"Full Credit": 0, "Partial Credit": 0, "No Credit": 0})
    student_data = defaultdict(lambda: defaultdict(lambda: {"Full Credit": 0, "Partial Credit": 0, "No Credit": 0}))
    student_names = []
    lexile_values = []
    proficiency_levels = []

    standard_pattern = re.compile(r"RC\|5\.RC\.\d+")

    for uploaded_file in uploaded_files:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        current_student = None
        for page in doc:
            text = page.get_text()
            lines = text.split("
")
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
                    if "v" in line:
                        standards_counts[current_standard]["Full Credit"] += 1
                        student_data[current_student][current_standard]["Full Credit"] += 1
                    elif "O" in line:
                        standards_counts[current_standard]["Partial Credit"] += 1
                        student_data[current_student][current_standard]["Partial Credit"] += 1
                    elif "X" in line:
                        standards_counts[current_standard]["No Credit"] += 1
                        student_data[current_student][current_standard]["No Credit"] += 1

    # Dashboard metrics
    total_students = len(set(student_names))
    avg_lexile = int(sum(lexile_values) / len(lexile_values)) if lexile_values else 0
    at_above = sum(1 for level in proficiency_levels if "At" in level or "Above" in level)
    needs_support = total_students - at_above
    at_above_pct = (at_above / total_students) * 100 if total_students else 0
    needs_support_pct = (needs_support / total_students) * 100 if total_students else 0

    # Dashboard cards
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.markdown(f'<div><h3>{total_students}</h3><p>Total Students</p></div>', unsafe_allow_html=True)
    st.markdown(f'<div><h3>{at_above_pct:.1f}%</h3><p>At/Above Proficiency</p></div>', unsafe_allow_html=True)
    st.markdown(f'<div><h3>{needs_support_pct:.1f}%</h3><p>Needs Support</p></div>', unsafe_allow_html=True)
    st.markdown(f'<div><h3>{avg_lexile}L</h3><p>Average Lexile</p></div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

    # Class Overview Table
    st.subheader("Academic Standards Performance - Class Overview")
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

    st.markdown('<div class="legend">Legend: ✓ = Full credit | O = Partial credit | X = No credit</div>', unsafe_allow_html=True)

    # Per-student breakdown
    st.subheader("Academic Standards Performance - By Student")
    for name in set(student_names):
        with st.expander(name):
            student_rows = []
            for standard, counts in student_data[name].items():
                total_tests = sum(counts.values())
                success_rate = (counts["Full Credit"] / total_tests * 100) if total_tests > 0 else 0
                student_rows.append([standard, total_tests, counts["Full Credit"], counts["Partial Credit"], counts["No Credit"], f"{success_rate:.0f}%"])
            student_df = pd.DataFrame(student_rows, columns=["Academic Standard", "Total Tests", "Full Credit (✓)", "Partial Credit (O)", "No Credit (X)", "Success Rate"])
            st.table(student_df)

    # Download CSV
    csv = df.to_csv(index=False).encode("utf-8")
    st.download_button("Download Class Overview as CSV", csv, "class_overview.csv", "text/csv")

    # Chart for PDF
    fig, ax = plt.subplots()
    ax.bar(df["Academic Standard"], df["Success Rate"].str.replace("%", "").astype(float))
    ax.set_ylabel("Success Rate (%)")
    ax.set_title("Academic Standards Success Rate")

    # PDF Export
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

        # Dashboard summary
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 10, "Class Analytics Dashboard", ln=True)
        pdf.set_font("Arial", "", 10)
        pdf.cell(0, 8, f"Total Students: {total_students}", ln=True)
        pdf.cell(0, 8, f"At/Above Proficiency: {at_above_pct:.1f}%", ln=True)
        pdf.cell(0, 8, f"Needs Support: {needs_support_pct:.1f}%", ln=True)
        pdf.cell(0, 8, f"Average Lexile: {avg_lexile}L", ln=True)
        pdf.ln(10)

        # Class Overview Table
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 10, "Class Overview", ln=True)
        pdf.set_font("Arial", "", 10)
        for i, row in df.iterrows():
            pdf.cell(0, 8, f"{row['Academic Standard']} | Students: {row['Students']} | Full: {row['Full Credit (✓)']} | Partial: {row['Partial Credit (O)']} | No: {row['No Credit (X)']} | Success: {row['Success Rate']}", ln=True)

        # Chart
        img_buffer = io.BytesIO()
        fig.savefig(img_buffer, format="png")
        img_buffer.seek(0)
        pdf.image(img_buffer, x=10, y=pdf.get_y() + 10, w=180)
        pdf.ln(80)

        # Per-student breakdown
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 10, "Per-Student Breakdown", ln=True)
        pdf.set_font("Arial", "", 10)
        for name in set(student_names):
            pdf.cell(0, 8, f"Student: {name}", ln=True)
            for standard, counts in student_data[name].items():
                total_tests = sum(counts.values())
                success_rate = (counts['Full Credit'] / total_tests * 100) if total_tests > 0 else 0
                pdf.cell(0, 8, f"  {standard} | Full: {counts['Full Credit']} | Partial: {counts['Partial Credit']} | No: {counts['No Credit']} | Success: {success_rate:.0f}%", ln=True)
            pdf.ln(5)

        return pdf.output(dest="S").encode("latin-1")

    pdf_bytes = create_pdf()
    st.download_button("Download Full Report as PDF", pdf_bytes, "ILEARN_Analytics_Report.pdf", "application/pdf")
