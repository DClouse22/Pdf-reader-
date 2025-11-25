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
    """Parser using vector graphics detection for symbols"""
    
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
        
        current_student = None
        students_found = []
        
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text()
            
            # Check for student name
            student_info = self._extract_student_info(text)
            if student_info['name']:
                current_student = student_info['name']
                if current_student not in self.student_data:
                    self.student_data[current_student] = {
                        'lexile': student_info['lexile'],
                        'proficiency': student_info['proficiency'],
                        'standards': defaultdict(lambda: {'correct': 0, 'incorrect': 0, 'partial': 0})
                    }
                    students_found.append(current_student)
            
            # Extract standards using vector graphics detection
            if current_student and 'RC|5.RC' in text:
                self._extract_standards_with_vectors(page, current_student)
        
        doc.close()
        
        if students_found:
            self.errors.append(f"✅ Found {len(students_found)} students: {', '.join(students_found)}")
    
    def _extract_student_info(self, text):
        """Extract student name, lexile, and proficiency"""
        info = {'name': '', 'lexile': 0, 'proficiency': ''}
        
        lines = text.split('\n')
        for line in lines:
            if line.startswith('Name:'):
                name = line.replace('Name:', '').strip()
                if name and len(name) > 2:
                    info['name'] = name
            elif 'Lexile® Measure Range Lower Limit:' in line:
                lex_match = re.search(r'(\d+)L', line)
                if lex_match:
                    info['lexile'] = int(lex_match.group(1))
            elif line.startswith('Performance Level:'):
                info['proficiency'] = line.replace('Performance Level:', '').strip()
        
        return info
    
    def _extract_standards_with_vectors(self, page, student_name):
        """Extract standards by analyzing vector graphics (drawing paths)"""
        
        # Get text blocks with positions
        blocks = page.get_text("dict")["blocks"]
        
        # Get drawing commands (vector graphics)
        drawings = page.get_drawings()
        
        # Extract text blocks that contain standards
        standard_blocks = []
        for block in blocks:
            if "lines" in block:
                for line in block["lines"]:
                    for span in line["spans"]:
                        text = span["text"]
                        if re.search(r'RC\|5\.RC\.\d+', text):
                            # Found a standard - store its position
                            bbox = span["bbox"]  # (x0, y0, x1, y1)
                            standard_match = re.search(r'(RC\|5\.RC\.\d+)', text)
                            if standard_match:
                                standard_blocks.append({
                                    'standard': standard_match.group(1),
                                    'y': bbox[1],  # y0 position
                                    'y_end': bbox[3],  # y1 position
                                    'bbox': bbox
                                })
        
        # Now match drawing symbols to standards based on Y position
        standards_found = 0
        symbols_found = 0
        
        for std_block in standard_blocks:
            standard = std_block['standard']
            std_y = std_block['y']
            std_y_end = std_block['y_end']
            standards_found += 1
            
            # Find drawings on the same row (similar Y coordinate)
            # Table symbols should be on the right side of the page
            symbol_type = None
            
            for drawing in drawings:
                draw_rect = drawing.get('rect', None)
                if not draw_rect:
                    continue
                
                draw_y = draw_rect.y0
                draw_y_end = draw_rect.y1
                draw_x = draw_rect.x0
                
                # Check if drawing is on the same row as the standard
                # Allow some tolerance in Y position (±10 points)
                if abs(draw_y - std_y) < 15 or (std_y <= draw_y <= std_y_end):
                    # Drawing is on same row
                    # Now analyze what type of symbol it is
                    
                    # Get drawing properties
                    fill_color = drawing.get('fill', None)
                    stroke_color = drawing.get('color', None)
                    items = drawing.get('items', [])
                    
                    # Checkmark: usually has diagonal lines (paths)
                    # X: has crossing diagonal lines
                    # Circle: has curved paths or is circular
                    
                    # Count line segments
                    line_count = sum(1 for item in items if item[0] == 'l')  # line
                    curve_count = sum(1 for item in items if item[0] in ['c', 'qu'])  # curves
                    
                    # Heuristics:
                    # - Checkmark: 2 lines forming a V shape
                    # - X: 2 lines forming an X (crossing)
                    # - Circle: curves (no lines) or many line segments forming circle
                    
                    if fill_color and curve_count == 0 and line_count == 2:
                        # Likely a checkmark (V shape) or X
                        # Need to analyze the angle/direction
                        # For now, assume checkmark if filled
                        symbol_type = 'correct'
                        symbols_found += 1
                        break
                    elif stroke_color and not fill_color and line_count >= 2:
                        # X is usually stroked (outline) not filled
                        symbol_type = 'incorrect'
                        symbols_found += 1
                        break
                    elif curve_count > 0 or line_count > 4:
                        # Circle (has curves or many line segments)
                        symbol_type = 'partial'
                        symbols_found += 1
                        break
            
            # If we found a symbol type, record it
            if symbol_type:
                self.standards_summary[standard][symbol_type] += 1
                self.student_data[student_name]['standards'][standard][symbol_type] += 1
        
        if standards_found > 0:
            self.errors.append(f"📊 {student_name}: {standards_found} standards, {symbols_found} vector symbols detected")

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
    st.markdown("**Using Vector Graphics Detection**")
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
        
        st.markdown("---")
        st.info("This version uses vector graphics detection to identify checkmarks and X's!")
    
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
        with st.expander("ℹ️ Processing Information", expanded=True):
            for error in parser.errors:
                if error.startswith("✅") or error.startswith("📊"):
                    st.success(error)
                else:
                    st.warning(error)
    
    if not parser.student_data:
        st.error("❌ No student data found")
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
        st.warning("⚠️ No standards data extracted")
        st.info("Vector symbols were not detected. The PDF may use a different format.")
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
