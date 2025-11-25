import streamlit as st
import fitz
import re
import pandas as pd
from collections import defaultdict
from fpdf import FPDF
import io
import plotly.express as px
from datetime import datetime
import cv2
import numpy as np
from pdf2image import convert_from_bytes
from PIL import Image

st.set_page_config(page_title="ILEARN Analytics Tool - OCR", page_icon="📊", layout="wide")

st.markdown("""
<style>
.main > div {padding-top: 2rem;}
.stMetric {background-color: #f0f2f6; padding: 15px; border-radius: 10px;}
h1 {color: #1f77b4;}
</style>
""", unsafe_allow_html=True)

class SymbolDetector:
    """Detect checkmark symbols using image processing"""
    
    def __init__(self):
        self.debug_images = []
    
    def detect_symbols_in_region(self, image_array, x, y, w, h, debug=False):
        """
        Detect symbols (checkmarks, X, O) in a specific region of the image
        Returns: 'correct', 'incorrect', 'partial', or None
        """
        # Extract region
        region = image_array[y:y+h, x:x+w]
        
        if region.size == 0:
            return None
        
        # Convert to grayscale
        if len(region.shape) == 3:
            gray = cv2.cvtColor(region, cv2.COLOR_RGB2GRAY)
        else:
            gray = region
        
        # Threshold to get black marks
        _, binary = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY_INV)
        
        # Count black pixels (marks)
        black_pixel_ratio = np.sum(binary > 0) / binary.size
        
        if debug:
            self.debug_images.append({
                'region': region,
                'binary': binary,
                'ratio': black_pixel_ratio
            })
        
        # If very few black pixels, it's empty
        if black_pixel_ratio < 0.05:
            return None
        
        # Analyze shape characteristics
        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        if not contours:
            return None
        
        # Get the largest contour
        largest_contour = max(contours, key=cv2.contourArea)
        area = cv2.contourArea(largest_contour)
        
        if area < 50:  # Too small
            return None
        
        # Analyze shape
        perimeter = cv2.arcLength(largest_contour, True)
        circularity = 4 * np.pi * area / (perimeter * perimeter) if perimeter > 0 else 0
        
        # Checkmark (v): angular, not circular, moderate complexity
        # X: two diagonal lines, angular
        # O (circle): high circularity
        
        if circularity > 0.7:  # Circular shape = O (partial)
            return 'partial'
        elif black_pixel_ratio > 0.15:  # Dense mark = X (incorrect)
            return 'incorrect'
        elif black_pixel_ratio > 0.08:  # Moderate mark = checkmark (correct)
            return 'correct'
        
        return None

class ILEARNOCRParser:
    """Parser using OCR and computer vision to extract symbols"""

    def __init__(self):
        self.student_data = defaultdict(lambda: {
            'name': '',
            'lexile': 0,
            'proficiency': '',
            'standards': defaultdict(lambda: {'correct': 0, 'incorrect': 0, 'partial': 0})
        })
        self.standards_summary = defaultdict(lambda: {'correct': 0, 'incorrect': 0, 'partial': 0, 'total_tests': 0})
        self.errors = []
        self.symbol_detector = SymbolDetector()

    def parse_files(self, uploaded_files):
        progress_bar = st.progress(0)
        status_text = st.empty()

        for idx, uploaded_file in enumerate(uploaded_files):
            status_text.text(f"Processing {uploaded_file.name}...")
            try:
                self._parse_single_file(uploaded_file)
            except Exception as e:
                self.errors.append(f"Error in {uploaded_file.name}: {str(e)}")
                st.error(f"Error: {str(e)}")

            progress_bar.progress((idx + 1) / len(uploaded_files))

        status_text.text("✅ Complete!")
        return self

    def _parse_single_file(self, uploaded_file):
        """Parse PDF using both text extraction and OCR"""
        
        debug = st.session_state.get('debug_mode', False)
        
        # First, extract text normally for student info
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        current_student = None
        
        # Extract basic info from text
        for page in doc:
            text = page.get_text()
            lines = text.split("\n")

            for line in lines:
                if line.strip().startswith("Name:"):
                    name_part = line.split("Name:")[-1].strip()
                    if name_part and len(name_part) > 2:
                        current_student = name_part
                        self.student_data[current_student]['name'] = current_student
                        if debug:
                            st.success(f"Found student: {current_student}")

                if current_student and ("Lexile" in line and "Lower Limit:" in line):
                    lex_match = re.search(r'(\d+)L', line)
                    if lex_match:
                        self.student_data[current_student]['lexile'] = int(lex_match.group(1))

                if current_student and line.strip().startswith("Performance Level:"):
                    prof = line.split("Performance Level:")[-1].strip()
                    self.student_data[current_student]['proficiency'] = prof

        doc.close()
        
        if not current_student:
            self.errors.append("Could not find student name in PDF")
            return
        
        # Now convert PDF to images for OCR
        uploaded_file.seek(0)  # Reset file pointer
        pdf_bytes = uploaded_file.read()
        
        try:
            # Convert PDF pages to images (lower DPI for speed, increase to 300 for better accuracy)
            images = convert_from_bytes(pdf_bytes, dpi=200)
            
            if debug:
                st.write(f"Converted {len(images)} pages to images")
            
            # Process pages that contain performance tables (typically pages 3-4, 7-8, etc.)
            for page_num, image in enumerate(images):
                if debug:
                    st.write(f"**Processing page {page_num + 1}**")
                
                # Convert PIL image to numpy array
                img_array = np.array(image)
                
                # Extract text with positions using PyMuPDF for this page
                doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                page = doc[page_num]
                text = page.get_text()
                
                # Check if this is a performance table page
                if 'Student Performance*' not in text and 'Performance Level Descriptor' not in text:
                    continue
                
                if debug:
                    st.info(f"Page {page_num + 1} contains performance table")
                
                # Parse the table structure from text
                lines = text.split("\n")
                standards_in_page = []
                
                table_started = False
                for i, line in enumerate(lines):
                    if 'Student Performance*' in line or 'Performance Level Descriptor' in line:
                        table_started = True
                    
                    if table_started:
                        standard_match = re.search(r'(RC\|\d+\.RC\.\d+)', line)
                        if standard_match:
                            standards_in_page.append(standard_match.group(1))
                
                if debug:
                    st.write(f"Found {len(standards_in_page)} standards on this page")
                
                # Get text positions using PyMuPDF
                blocks = page.get_text("dict")["blocks"]
                
                # Find "Student Performance*" column location
                perf_col_x = None
                for block in blocks:
                    if "lines" in block:
                        for line in block["lines"]:
                            for span in line["spans"]:
                                if "Performance*" in span["text"]:
                                    perf_col_x = span["bbox"][0]  # x position
                                    break
                
                if not perf_col_x:
                    if debug:
                        st.warning(f"Could not locate Performance column on page {page_num + 1}")
                    continue
                
                # For each standard, find its Y position and check for symbol in performance column
                for standard in standards_in_page:
                    standard_y = None
                    
                    # Find Y position of this standard
                    for block in blocks:
                        if "lines" in block:
                            for line in block["lines"]:
                                for span in line["spans"]:
                                    if standard in span["text"]:
                                        standard_y = span["bbox"][1]  # y position
                                        break
                    
                    if standard_y:
                        # Define region to check (performance column at this standard's row)
                        # Convert PDF coordinates to image coordinates
                        page_height = page.rect.height
                        image_height = img_array.shape[0]
                        scale = image_height / page_height
                        
                        # Approximate position of symbol in performance column
                        symbol_x = int(perf_col_x * scale * 1.5)  # Adjust multiplier based on table layout
                        symbol_y = int(standard_y * scale)
                        symbol_w = int(30 * scale)  # Symbol width
                        symbol_h = int(30 * scale)  # Symbol height
                        
                        # Ensure coordinates are within bounds
                        symbol_x = max(0, min(symbol_x, img_array.shape[1] - symbol_w))
                        symbol_y = max(0, min(symbol_y, img_array.shape[0] - symbol_h))
                        
                        # Detect symbol in this region
                        symbol_type = self.symbol_detector.detect_symbols_in_region(
                            img_array, symbol_x, symbol_y, symbol_w, symbol_h, debug=debug
                        )
                        
                        if symbol_type:
                            self.student_data[current_student]['standards'][standard][symbol_type] += 1
                            self.standards_summary[standard][symbol_type] += 1
                            self.standards_summary[standard]['total_tests'] += 1
                            
                            if debug:
                                st.success(f"  {standard}: {symbol_type}")
                        elif debug:
                            st.warning(f"  {standard}: No symbol detected")
                
                doc.close()
                
        except Exception as e:
            self.errors.append(f"OCR Error: {str(e)}")
            if debug:
                st.error(f"OCR processing failed: {str(e)}")

# Report generator (same as before)
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

def main():
    st.title("📊 ILEARN Analytics Tool - OCR Version")
    st.markdown("**Using Computer Vision to Extract Performance Symbols**")
    
    st.info("""
    This version uses **OCR and image recognition** to detect the checkmark symbols (v, O, X) 
    that are rendered as graphics in the PDF.
    
    ⚠️ **Note:** This is an experimental approach and may require manual verification.
    """)
    
    st.markdown("---")

    with st.sidebar:
        st.header("⚙️ Settings")
        school_name = st.text_input("School Name:", placeholder="Your school")
        logo_file = st.file_uploader("School Logo:", type=["png", "jpg", "jpeg"])
        
        st.markdown("---")
        st.markdown("### 🐛 Debug")
        debug_mode = st.checkbox("Enable Debug Mode", value=False, 
                                 help="Shows detailed OCR processing information")
        st.session_state['debug_mode'] = debug_mode

        st.markdown("---")
        st.markdown("### 📖 About")
        st.markdown("Analyzes ILEARN ELA Checkpoint reports using OCR")

    uploaded_files = st.file_uploader("📁 Upload ILEARN PDF Reports", type="pdf", accept_multiple_files=True)

    if not uploaded_files:
        st.info("👆 Upload PDF files to begin")
        st.stop()

    with st.spinner("Processing PDFs with OCR (this may take a minute)..."):
        parser = ILEARNOCRParser()
        parser.parse_files(uploaded_files)

    if parser.errors:
        with st.expander("⚠️ Warnings"):
            for error in parser.errors:
                st.warning(error)

    if not parser.student_data:
        st.error("No data found in PDFs")
        st.stop()

    if not parser.standards_summary:
        st.warning("No performance data could be extracted. Try enabling Debug Mode to see what's happening.")
        # Still show student info
        students = list(parser.student_data.keys())
        st.subheader("📋 Students Found")
        for student in students:
            info = parser.student_data[student]
            st.write(f"**{student}** - Lexile: {info['lexile']}L, Proficiency: {info['proficiency']}")
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
        st.warning("No standards performance data extracted")
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
