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
# PARSER CLASS FOR TABLE-BASED PDFs
# =============================
class ILEARNTableParser:
    """Parser specifically designed for table-based ILEARN PDF reports"""

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
        
        debug = st.session_state.get('debug_mode', False)

        for page_num, page in enumerate(doc):
            text = page.get_text()
            lines = text.split("\n")
            
            if debug:
                st.write(f"**Page {page_num + 1} Sample:**")
                st.text("\n".join(lines[:30]))

            # Parse student info from first page
            for i, line in enumerate(lines):
                # Extract student name - format: "Name: Last, First"
                if line.strip().startswith("Name:"):
                    name_part = line.split("Name:")[-1].strip()
                    if name_part and len(name_part) > 2:
                        current_student = name_part
                        self.student_data[current_student]['name'] = current_student
                        if debug:
                            st.success(f"Found student: {current_student}")

                # Extract Lexile - format: "Lexile® Measure Range Lower Limit: 725L"
                if current_student and ("Lexile" in line and "Lower Limit:" in line):
                    lex_match = re.search(r'(\d+)L', line)
                    if lex_match:
                        self.student_data[current_student]['lexile'] = int(lex_match.group(1))
                        if debug:
                            st.success(f"Found Lexile: {lex_match.group(1)}L")

                # Extract Performance Level - format: "Performance Level: Approaching Proficiency"
                if current_student and line.strip().startswith("Performance Level:"):
                    prof = line.split("Performance Level:")[-1].strip()
                    self.student_data[current_student]['proficiency'] = prof
                    if debug:
                        st.success(f"Found proficiency: {prof}")

            # Parse standards table data using improved strategy
            # Strategy: Find table sections and group standards with their symbols
            
            # First, find where performance tables start
            table_started = False
            standards_in_page = []
            symbols_in_page = []
            
            for i, line in enumerate(lines):
                # Detect start of performance table
                if 'Student Performance*' in line or 'Performance Level Descriptor' in line:
                    table_started = True
                    if debug:
                        st.info(f"Table detected at line {i}")
                
                # If we're in a table, collect standards and symbols separately
                if table_started:
                    # Collect standards
                    standard_match = re.search(r'(RC\|\d+\.RC\.\d+)', line)
                    if standard_match:
                        standards_in_page.append((i, standard_match.group(1)))
                        if debug:
                            st.write(f"Line {i}: Found standard {standard_match.group(1)}")
                    
                    # Collect symbols - check for any of the performance symbols
                    if '✓' in line or '✔' in line:
                        symbols_in_page.append((i, 'correct', '✓'))
                        if debug:
                            st.write(f"Line {i}: Found ✓")
                    elif '✗' in line or '✘' in line or '❌' in line:
                        symbols_in_page.append((i, 'incorrect', '✗'))
                        if debug:
                            st.write(f"Line {i}: Found ✗")
                    elif '⊖' in line or '◯' in line or '○' in line:
                        symbols_in_page.append((i, 'partial', '⊖'))
                        if debug:
                            st.write(f"Line {i}: Found ⊖")
            
            # Now match standards with symbols based on proximity
            if current_student and standards_in_page:
                if debug:
                    st.write(f"**Matching {len(standards_in_page)} standards with {len(symbols_in_page)} symbols**")
                
                for std_idx, (std_line, standard) in enumerate(standards_in_page):
                    # Find the closest symbol that comes after this standard
                    # but before the next standard (if any)
                    next_std_line = standards_in_page[std_idx + 1][0] if std_idx + 1 < len(standards_in_page) else len(lines)
                    
                    found_symbol = False
                    for sym_line, sym_type, sym_char in symbols_in_page:
                        # Symbol should be between current standard and next standard
                        if std_line <= sym_line < next_std_line:
                            # Record the result
                            self.student_data[current_student]['standards'][standard][sym_type] += 1
                            self.standards_summary[standard][sym_type] += 1
                            self.standards_summary[standard]['total_tests'] += 1
                            found_symbol = True
                            
                            if debug:
                                st.success(f"  {standard}: {sym_char} {sym_type}")
                            
                            # Remove this symbol so it's not matched again
                            symbols_in_page.remove((sym_line, sym_type, sym_char))
                            break
                    
                    if not found_symbol and debug:
                        st.warning(f"  {standard}: No symbol found")

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
        pdf.multi_cell(0, 6, f"Total Students: {metrics['total_students']}\n"
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
    st.title("📊 ILEARN Analytics Tool v2")
    st.markdown("**Optimized for Indiana ILEARN Table-Based Reports**")
    st.markdown("---")

    # Sidebar
    with st.sidebar:
        st.header("⚙️ Settings")
        school_name = st.text_input("School Name:", placeholder="Your school")
        logo_file = st.file_uploader("School Logo:", type=["png", "jpg", "jpeg"])
        
        st.markdown("---")
        st.markdown("### 🐛 Debug")
        debug_mode = st.checkbox("Enable Debug Mode", value=False, 
                                 help="Shows detailed parsing information")
        st.session_state['debug_mode'] = debug_mode

        st.markdown("---")
        st.markdown("### 📖 About")
        st.markdown("Analyzes ILEARN ELA Checkpoint reports with table-based data")

    # File upload
    uploaded_files = st.file_uploader("📁 Upload ILEARN PDF Reports", type="pdf", accept_multiple_files=True)

    if not uploaded_files:
        st.info("👆 Upload PDF files to begin")
        st.stop()

    # Parse files
    with st.spinner("Processing..."):
        parser = ILEARNTableParser()
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
