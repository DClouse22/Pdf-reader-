
import streamlit as st
import fitz
import re
import pandas as pd
from collections import defaultdict
from fpdf import FPDF
import io
import plotly.express as px
from datetime import datetime

# =============================
# PAGE CONFIGURATION
# =============================
st.set_page_config(page_title="ILEARN Analytics Tool", page_icon="📊", layout="wide")

# =============================
# CUSTOM CSS
# =============================
st.markdown("""
<style>
.main > div {padding-top: 2rem;}
.stMetric {background-color: #f0f2f6; padding: 15px; border-radius: 10px;}
h1 {color: #1f77b4;}
</style>
""", unsafe_allow_html=True)

# =============================
# PARSER CLASS
# =============================
class ILEARNParser:
    """Parser for ILEARN PDF reports"""

    def __init__(self):
        self.student_data = defaultdict(lambda: {
            'name': '',
            'lexile': 0,
            'proficiency': '',
            'standards': defaultdict(lambda: {'correct': 0, 'incorrect': 0, 'partial': 0})
        })
        self.standards_summary = defaultdict(lambda: {'correct': 0, 'incorrect': 0, 'partial': 0, 'total_tests': 0})
        self.errors = []

    def parse_files(self, uploaded_files):
        progress_bar = st.progress(0)
        status_text = st.empty()

        for idx, uploaded_file in enumerate(uploaded_files):
            status_text.text(f"Processing {uploaded_file.name}...")
            try:
                self._parse_single_file(uploaded_file)
            except Exception as e:
                self.errors.append(f"Error in {uploaded_file.name}: {str(e)}")

            progress_bar.progress((idx + 1) / len(uploaded_files))

        status_text.text("✅ Complete!")
        return self

    def _parse_single_file(self, uploaded_file):
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        current_student = None

        for page in doc:
            text = page.get_text()
            lines = text.split("\n")

            for i, line in enumerate(lines):
                # Extract student name
                if line.strip().startswith(("Name:", "Student Name:")):
                    current_student = line.split(":")[-1].strip()
                    self.student_data[current_student]['name'] = current_student

                # Extract Lexile
                if "Lexile" in line:
                    lex_match = re.search(r"(\d+)L", line)
                    if lex_match:
                        self.student_data[current_student]['lexile'] = int(lex_match.group(1))

                # Extract Performance Level
                if line.strip().startswith("Performance Level:"):
                    prof = line.split(":")[-1].strip()
                    self.student_data[current_student]['proficiency'] = prof

                # Extract standards
                standard_match = re.search(r'(RC\.5\.RC\.\d+)', line)
                if standard_match and current_student:
                    standard = standard_match.group(1)
                    check_lines = lines[i:i+3] if i < len(lines)-2 else lines[i:]
                    context = " ".join(check_lines)

                    # Normalize symbols
                    if any(sym in context for sym in ["✓", "✔", "v"]):
                        self.student_data[current_student]['standards'][standard]['correct'] += 1
                        self.standards_summary[standard]['correct'] += 1
                    elif any(sym in context for sym in ["✗", "✘", "X"]):
                        self.student_data[current_student]['standards'][standard]['incorrect'] += 1
                        self.standards_summary[standard]['incorrect'] += 1
                    elif any(sym in context for sym in ["⊖", "O", "○"]):
                        self.student_data[current_student]['standards'][standard]['partial'] += 1
                        self.standards_summary[standard]['partial'] += 1

                    self.standards_summary[standard]['total_tests'] += 1

        doc.close()

# =============================
# REPORT GENERATOR
# =============================
class ReportGenerator:
    def __init__(self, school_name="", logo_file=None):
        self.school_name = school_name
        self.logo_file = logo_file

    def create_pdf(self, df, metrics):
        pdf = FPDF()
        pdf.add_page()

        if self.logo_file:
            try:
                img_buffer = io.BytesIO(self.logo_file.getvalue())
                pdf.image(img_buffer, x=10, y=8, w=30)
            except:
                pass

        pdf.set_font("Arial", "B", 18)
        pdf.cell(0, 10, "ILEARN Analytics Report", ln=True, align="C")

        if self.school_name:
            pdf.set_font("Arial", "I", 14)
            pdf.cell(0, 8, self.school_name, ln=True, align="C")

        pdf.set_font("Arial", "", 10)
        pdf.cell(0, 6, f"Generated: {datetime.now().strftime('%B %d, %Y')}", ln=True, align="C")
        pdf.ln(10)

        pdf.set_font("Arial", "B", 14)
        pdf.cell(0, 10, "Summary", ln=True)
        pdf.set_font("Arial", "", 11)
        pdf.multi_cell(0, 6, f"Total Students: {metrics['total_students']}
"
                              f"Average Lexile: {metrics['avg_lexile']}L")
        pdf.ln(5)

        pdf.set_font("Arial", "B", 14)
        pdf.cell(0, 10, "Standards Performance", ln=True)

        for _, row in df.iterrows():
            pdf.set_font("Arial", "", 10)
            pdf.cell(0, 6, f"{row['Standard']}: {row['Success Rate']}", ln=True)

        return pdf.output(dest="S").encode("latin-1")

# =============================
# MAIN APPLICATION
# =============================
def main():
    st.title("📊 ILEARN Analytics Tool")
    st.markdown("**Designed for Indiana ILEARN Checkpoint Reports**")
    st.markdown("---")

    # Sidebar
    with st.sidebar:
        st.header("⚙️ Settings")
        school_name = st.text_input("School Name:", placeholder="Your school")
        logo_file = st.file_uploader("School Logo:", type=["png", "jpg", "jpeg"])

        st.markdown("---")
        st.markdown("### 📖 About")
        st.markdown("Analyzes ILEARN ELA Checkpoint reports")

    # File upload
    uploaded_files = st.file_uploader("📁 Upload ILEARN PDF Reports", type="pdf", accept_multiple_files=True)

    if not uploaded_files:
        st.info("👆 Upload PDF files to begin")
        st.stop()

    # Parse files
    with st.spinner("Processing..."):
        parser = ILEARNParser()
        parser.parse_files(uploaded_files)

    # Show errors
    if parser.errors:
        with st.expander("⚠️ Warnings"):
            for error in parser.errors:
                st.warning(error)

    if not parser.student_data:
        st.error("No data found in PDFs")
        st.stop()

    if not parser.standards_summary:
        st.error("No standards found")
        st.stop()

    # Calculate metrics
    students = list(parser.student_data.keys())
    total_students = len(students)

    lexile_values = [parser.student_data[s]['lexile'] for s in students if parser.student_data[s]['lexile'] > 0]
    avg_lexile = int(sum(lexile_values) / len(lexile_values)) if lexile_values else 0

    prof_levels = [parser.student_data[s]['proficiency'] for s in students if parser.student_data[s]['proficiency']]
    at_above = sum(1 for p in prof_levels if "At" in p or "Above" in p)
    at_above_pct = (at_above / total_students * 100) if total_students else 0
    needs_support_pct = 100 - at_above_pct

    metrics = {
        'total_students': total_students,
        'avg_lexile': avg_lexile,
        'at_above_pct': at_above_pct,
        'needs_support_pct': needs_support_pct
    }

    # Dashboard
    st.subheader("📈 Class Overview")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Students", total_students)
    col2.metric("At/Above Prof.", f"{at_above_pct:.1f}%")
    col3.metric("Needs Support", f"{needs_support_pct:.1f}%")
    col4.metric("Avg Lexile", f"{avg_lexile}L")

    st.markdown("---")

    # Standards analysis
    st.subheader("📚 Standards Performance")
    data = []
    for standard, counts in parser.standards_summary.items():
        total = counts['correct'] + counts['incorrect'] + counts['partial']
        if total > 0:
            success_rate = (counts['correct'] / total * 100)
            data.append({
                'Standard': standard,
                'Correct (✓)': counts['correct'],
                'Partial (⊖)': counts['partial'],
                'Incorrect (✗)': counts['incorrect'],
                'Success Rate': f"{success_rate:.1f}%",
                'Success Rate Value': success_rate
            })

    if not data:
        st.warning("No standards performance data available")
        st.stop()

    df = pd.DataFrame(data)
    df = df.sort_values('Success Rate Value', ascending=False)

    st.dataframe(df.drop('Success Rate Value', axis=1), use_container_width=True, hide_index=True)

    # Chart
    fig = px.bar(df, x='Standard', y='Success Rate Value', title='Standards Success Rate',
                 labels={'Success Rate Value': 'Success Rate (%)'}, color='Success Rate Value',
                 color_continuous_scale='RdYlGn', range_color=[0, 100])
    fig.update_layout(height=400)
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # Individual students
    st.subheader("👩‍🎓 Individual Students")
    for student in sorted(students):
        info = parser.student_data[student]
        lexile_display = f"{info['lexile']}L" if info['lexile'] > 0 else "N/A"
        prof_display = info['proficiency'] if info['proficiency'] else "N/A"

        with st.expander(f"📋 {student} - Lexile: {lexile_display} | {prof_display}"):
            if info['standards']:
                student_rows = []
                for standard, counts in info['standards'].items():
                    total = counts['correct'] + counts['incorrect'] + counts['partial']
                    success = (counts['correct'] / total * 100) if total > 0 else 0
                    student_rows.append({
                        'Standard': standard,
                        'Correct': counts['correct'],
                        'Partial': counts['partial'],
                        'Incorrect': counts['incorrect'],
                        'Success Rate': f"{success:.1f}%"
                    })

                if student_rows:
                    st.dataframe(pd.DataFrame(student_rows), use_container_width=True, hide_index=True)
                else:
                    st.info("No standards data for this student")

    st.markdown("---")

    # Export
    st.subheader("💾 Export")
    col1, col2 = st.columns(2)

    with col1:
        csv = df.drop('Success Rate Value', axis=1).to_csv(index=False).encode("utf-8")
        st.download_button("📄 Download CSV", csv, f"ilearn_{datetime.now().strftime('%Y%m%d')}.csv", "text/csv")

    with col2:
        report_gen = ReportGenerator(school_name, logo_file)
        pdf_bytes = report_gen.create_pdf(df.drop('Success Rate Value', axis=1), metrics)
        st.download_button("📑 Download PDF", pdf_bytes, f"ilearn_{datetime.now().strftime('%Y%m%d')}.pdf", "application/pdf")

if __name__ == "__main__":
    main()
