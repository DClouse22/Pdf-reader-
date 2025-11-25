import streamlit as st
import fitz
import re
import pandas as pd
from collections import defaultdict
from fpdf import FPDF
import io
import plotly.express as px
from datetime import datetime

st.set_page_config(page_title="ILEARN Analytics Tool", page_icon="📊", layout="wide")

st.markdown("""
    <style>
    .main > div {padding-top: 2rem;}
    .stMetric {background-color: #f0f2f6; padding: 15px; border-radius: 10px;}
    </style>
""", unsafe_allow_html=True)

class ILEARNParser:
    """Parser for ILEARN checkpoint PDFs"""
    
    def __init__(self):
        self.student_data = {}
        self.standards_summary = defaultdict(lambda: {'correct': 0, 'incorrect': 0, 'partial': 0})
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
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()
            
            # Extract student info from first page
            if page_num == 0:
                student_info = self._extract_student_info(text)
                if student_info['name']:
                    student_name = student_info['name']
                    self.student_data[student_name] = {
                        'lexile': student_info['lexile'],
                        'proficiency': student_info['proficiency'],
                        'standards': defaultdict(lambda: {'correct': 0, 'incorrect': 0, 'partial': 0})
                    }
            
            # Extract standards from pages with tables (typically page 3+)
            if page_num >= 2:  # Standards tables start on page 3
                self._extract_standards_from_table(text, student_name if 'student_name' in locals() else None)
        
        doc.close()
    
    def _extract_student_info(self, text):
        """Extract student name, lexile, and proficiency from first page"""
        info = {'name': '', 'lexile': 0, 'proficiency': ''}
        
        lines = text.split('\n')
        for line in lines:
            if line.startswith('Name:'):
                info['name'] = line.replace('Name:', '').strip()
            elif 'Lexile® Measure Range Lower Limit:' in line:
                lex_match = re.search(r'(\d+)L', line)
                if lex_match:
                    info['lexile'] = int(lex_match.group(1))
            elif line.startswith('Performance Level:'):
                info['proficiency'] = line.replace('Performance Level:', '').strip()
        
        return info
    
    def _extract_standards_from_table(self, text, student_name):
        """Extract standards and performance from table pages"""
        lines = text.split('\n')
        
        # Find table rows with standards
        i = 0
        while i < len(lines):
            line = lines[i]
            
            # Look for standard pattern: RC|5.RC.X
            standard_match = re.search(r'(RC\|5\.RC\.\d+)', line)
            if standard_match:
                standard = standard_match.group(1)
                
                # The performance symbol should be in nearby lines
                # Look at the current line and next few lines for the symbol
                check_range = lines[i:min(i+5, len(lines))]
                combined_text = ' '.join(check_range)
                
                # Check for symbols - they might be actual unicode or text representations
                # ✓ checkmark (correct)
                # ✗ or X (incorrect)  
                # ⊖ or O (partial)
                
                # Also check for the words in the table
                if any(char in combined_text for char in ['✓', '✔', 'v']):
                    perf_type = 'correct'
                elif any(char in combined_text for char in ['✗', '✘', '×']):
                    perf_type = 'incorrect'
                elif any(char in combined_text for char in ['⊖', '◯', '○']):
                    perf_type = 'partial'
                else:
                    # If no symbol found, skip
                    i += 1
                    continue
                
                # Update counts
                self.standards_summary[standard][perf_type] += 1
                
                if student_name and student_name in self.student_data:
                    self.student_data[student_name]['standards'][standard][perf_type] += 1
            
            i += 1

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
        
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 8, "Class Summary", ln=True)
        pdf.set_font("Arial", "", 10)
        pdf.cell(0, 6, f"Total Students: {metrics['total_students']}", ln=True)
        pdf.cell(0, 6, f"Average Lexile: {metrics['avg_lexile']}L", ln=True)
        pdf.cell(0, 6, f"At/Above Proficiency: {metrics['at_above_pct']:.1f}%", ln=True)
        pdf.ln(5)
        
        pdf.set_font("Arial", "B", 12)
        pdf.cell(0, 8, "Standards Performance", ln=True)
        
        for _, row in df.iterrows():
            pdf.set_font("Arial", "", 9)
            pdf.cell(0, 5, f"{row['Standard']}: {row['Success Rate']}", ln=True)
        
        return pdf.output(dest="S").encode("latin-1")

def main():
    st.title("📊 ILEARN Analytics Tool")
    st.markdown("**For Indiana ILEARN ELA Checkpoint Reports**")
    st.markdown("---")
    
    with st.sidebar:
        st.header("⚙️ Settings")
        school_name = st.text_input("School Name:", placeholder="Your school")
        logo_file = st.file_uploader("School Logo:", type=["png", "jpg", "jpeg"])
        
        st.markdown("---")
        st.markdown("### 📖 How to Use")
        st.markdown("""
        1. Upload ILEARN PDF reports
        2. Review class metrics
        3. Analyze standards
        4. Export results
        """)
    
    uploaded_files = st.file_uploader(
        "📁 Upload ILEARN PDF Reports",
        type="pdf",
        accept_multiple_files=True
    )
    
    if not uploaded_files:
        st.info("👆 Upload PDF files to begin")
        st.stop()
    
    with st.spinner("Processing PDFs..."):
        parser = ILEARNParser()
        parser.parse_files(uploaded_files)
    
    if parser.errors:
        with st.expander("⚠️ Processing Warnings"):
            for error in parser.errors:
                st.warning(error)
    
    if not parser.student_data:
        st.error("❌ No student data found")
        st.info("Make sure PDFs are ILEARN checkpoint reports")
        st.stop()
    
    # Calculate metrics
    total_students = len(parser.student_data)
    
    lexile_values = [s['lexile'] for s in parser.student_data.values() if s['lexile'] > 0]
    avg_lexile = int(sum(lexile_values) / len(lexile_values)) if lexile_values else 0
    
    prof_levels = [s['proficiency'] for s in parser.student_data.values() if s['proficiency']]
    at_above = sum(1 for p in prof_levels if 'At' in p or 'Above' in p)
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
    
    # Standards summary
    st.subheader("📚 Standards Performance")
    
    if not parser.standards_summary:
        st.warning("⚠️ No standards data extracted from PDFs")
        st.info("""
        **Debug Tips:**
        - Make sure PDFs contain the standards performance tables
        - Tables should have columns: Academic Standard | Performance | Student Performance
        - Standards should be formatted as: RC|5.RC.1, RC|5.RC.2, etc.
        """)
        st.stop()
    
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
                'Total': total,
                'Success Rate': f"{success_rate:.1f}%",
                'Success Rate Value': success_rate
            })
    
    df = pd.DataFrame(data)
    df = df.sort_values('Success Rate Value', ascending=False)
    
    st.dataframe(df.drop('Success Rate Value', axis=1), use_container_width=True, hide_index=True)
    
    # Chart
    if len(df) > 0:
        fig = px.bar(
            df,
            x='Standard',
            y='Success Rate Value',
            title='Standards Success Rates',
            color='Success Rate Value',
            color_continuous_scale='RdYlGn',
            range_color=[0, 100]
        )
        fig.update_layout(height=400, showlegend=False)
        st.plotly_chart(fig, use_container_width=True)
    
    st.markdown("---")
    
    # Individual students
    st.subheader("👩‍🎓 Individual Students")
    
    for student_name in sorted(parser.student_data.keys()):
        student = parser.student_data[student_name]
        lexile_str = f"{student['lexile']}L" if student['lexile'] > 0 else "N/A"
        prof_str = student['proficiency'] if student['proficiency'] else "N/A"
        
        with st.expander(f"📋 {student_name} - Lexile: {lexile_str} | {prof_str}"):
            if student['standards']:
                rows = []
                for std, counts in student['standards'].items():
                    total = counts['correct'] + counts['incorrect'] + counts['partial']
                    success = (counts['correct'] / total * 100) if total > 0 else 0
                    rows.append({
                        'Standard': std,
                        'Correct': counts['correct'],
                        'Partial': counts['partial'],
                        'Incorrect': counts['incorrect'],
                        'Success Rate': f"{success:.1f}%"
                    })
                
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.info("No standards data for this student")
    
    st.markdown("---")
    
    # Export
    st.subheader("💾 Export Options")
    col1, col2 = st.columns(2)
    
    with col1:
        csv = df.drop('Success Rate Value', axis=1).to_csv(index=False).encode("utf-8")
        st.download_button(
            "📄 Download CSV",
            csv,
            f"ilearn_report_{datetime.now().strftime('%Y%m%d')}.csv",
            "text/csv",
            use_container_width=True
        )
    
    with col2:
        report_gen = ReportGenerator(school_name, logo_file)
        pdf_bytes = report_gen.create_pdf(df.drop('Success Rate Value', axis=1), metrics)
        st.download_button(
            "📑 Download PDF Report",
            pdf_bytes,
            f"ilearn_report_{datetime.now().strftime('%Y%m%d')}.pdf",
            "application/pdf",
            use_container_width=True
        )

if __name__ == "__main__":
    main()
