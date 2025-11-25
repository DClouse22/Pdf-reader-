import streamlit as st
import fitz
import re
import pandas as pd
from collections import defaultdict
from fpdf import FPDF
import io
import plotly.express as px
from datetime import datetime
from pdf2image import convert_from_bytes
from PIL import Image
import numpy as np

st.set_page_config(page_title="ILEARN Analytics Tool - OCR", page_icon="📊", layout="wide")

st.markdown("""
<style>
.main > div {padding-top: 2rem;}
.stMetric {background-color: #f0f2f6; padding: 15px; border-radius: 10px;}
h1 {color: #1f77b4;}
</style>
""", unsafe_allow_html=True)

class SimpleSymbolDetector:
    """Detect checkmark symbols using basic image analysis (no OpenCV)"""
    
    def detect_symbol_in_region(self, image, x, y, w, h, debug=False):
        """
        Detect symbols (v, X, O) in a specific region using PIL only
        Returns: 'correct', 'incorrect', 'partial', or None
        """
        try:
            # Crop region
            region = image.crop((x, y, x+w, y+h))
            
            # Convert to grayscale
            region_gray = region.convert('L')
            
            # Convert to numpy array for analysis
            pixels = np.array(region_gray)
            
            # Calculate average brightness (0=black, 255=white)
            avg_brightness = np.mean(pixels)
            
            # Calculate standard deviation (measure of contrast/mark presence)
            std_brightness = np.std(pixels)
            
            # Count dark pixels (potential marks)
            dark_pixels = np.sum(pixels < 200)
            total_pixels = pixels.size
            dark_ratio = dark_pixels / total_pixels if total_pixels > 0 else 0
            
            if debug:
                st.write(f"  Region analysis: avg={avg_brightness:.1f}, std={std_brightness:.1f}, dark_ratio={dark_ratio:.3f}")
            
            # If almost all white (no mark)
            if dark_ratio < 0.05:
                return None
            
            # Analyze the distribution of dark pixels to identify shape
            # Simple heuristics based on darkness ratio and contrast
            
            # High contrast + moderate darkness = likely checkmark
            if std_brightness > 60 and 0.08 < dark_ratio < 0.20:
                return 'correct'
            
            # Very dark = X (incorrect)
            if dark_ratio > 0.25:
                return 'incorrect'
            
            # Moderate darkness with good contrast = checkmark
            if dark_ratio > 0.12 and std_brightness > 50:
                return 'correct'
            
            # Light mark with some contrast = O (partial)
            if dark_ratio > 0.05 and std_brightness > 30:
                return 'partial'
            
            return None
            
        except Exception as e:
            if debug:
                st.error(f"Error detecting symbol: {e}")
            return None

class ILEARNOCRParser:
    """Parser using OCR and image analysis (no OpenCV required)"""

    def __init__(self):
        self.student_data = defaultdict(lambda: {
            'name': '',
            'lexile': 0,
            'proficiency': '',
            'standards': defaultdict(lambda: {'correct': 0, 'incorrect': 0, 'partial': 0})
        })
        self.standards_summary = defaultdict(lambda: {'correct': 0, 'incorrect': 0, 'partial': 0, 'total_tests': 0})
        self.errors = []
        self.detector = SimpleSymbolDetector()

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
        """Parse PDF using text extraction and image analysis"""
        
        debug = st.session_state.get('debug_mode', False)
        
        # First pass: Extract text for student info
        pdf_bytes = uploaded_file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        current_student = None
        
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

        if not current_student:
            self.errors.append("Could not find student name")
            doc.close()
            return
        
        # Second pass: Convert to images and detect symbols
        try:
            # Convert PDF to images (150 DPI for balance of speed and quality)
            images = convert_from_bytes(pdf_bytes, dpi=150)
            
            if debug:
                st.write(f"Converted {len(images)} pages to images")
            
            # Process each page
            for page_num, image in enumerate(images):
                page = doc[page_num]
                text = page.get_text()
                
                # Only process performance table pages
                if 'Student Performance*' not in text and 'Performance Level Descriptor' not in text:
                    continue
                
                if debug:
                    st.info(f"**Page {page_num + 1}** - Processing performance table")
                
                # Extract standards from text
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
                    st.write(f"Found {len(standards_in_page)} standards")
                
                # Get text positions
                blocks = page.get_text("dict")["blocks"]
                
                # Find performance column X position
                perf_col_x = None
                for block in blocks:
                    if "lines" in block:
                        for line in block["lines"]:
                            for span in line["spans"]:
                                if "Performance*" in span["text"]:
                                    perf_col_x = span["bbox"][2]  # Right edge of "Performance*" text
                                    break
                
                if not perf_col_x:
                    if debug:
                        st.warning("Could not locate Performance column")
                    continue
                
                # Calculate scale from PDF to image coordinates
                page_width = page.rect.width
                page_height = page.rect.height
                img_width, img_height = image.size
                scale_x = img_width / page_width
                scale_y = img_height / page_height
                
                # For each standard, find its position and check for symbol
                processed_standards = set()
                
                for block in blocks:
                    if "lines" not in block:
                        continue
                    
                    for line in block["lines"]:
                        for span in line["spans"]:
                            # Check if this span contains a standard
                            for standard in standards_in_page:
                                if standard in span["text"] and standard not in processed_standards:
                                    # Get standard position
                                    std_bbox = span["bbox"]
                                    std_y = std_bbox[1]  # Top of standard text
                                    
                                    # Calculate symbol region in image coordinates
                                    # Symbol should be to the right of the performance column header
                                    symbol_x = int(perf_col_x * scale_x) + 10  # Add offset
                                    symbol_y = int(std_y * scale_y) - 5  # Slight upward adjustment
                                    symbol_w = 40  # Symbol width in pixels
                                    symbol_h = 40  # Symbol height in pixels
                                    
                                    # Ensure within bounds
                                    symbol_x = max(0, min(symbol_x, img_width - symbol_w))
                                    symbol_y = max(0, min(symbol_y, img_height - symbol_h))
                                    
                                    # Detect symbol
                                    if debug:
                                        st.write(f"Checking {standard} at image pos ({symbol_x}, {symbol_y})")
                                    
                                    symbol_type = self.detector.detect_symbol_in_region(
                                        image, symbol_x, symbol_y, symbol_w, symbol_h, debug=debug
                                    )
                                    
                                    if symbol_type:
                                        self.student_data[current_student]['standards'][standard][symbol_type] += 1
                                        self.standards_summary[standard][symbol_type] += 1
                                        self.standards_summary[standard]['total_tests'] += 1
                                        processed_standards.add(standard)
                                        
                                        if debug:
                                            st.success(f"✓ {standard}: {symbol_type}")
                                    elif debug:
                                        st.warning(f"✗ {standard}: No symbol detected")
                                    
                                    break
        
        except Exception as e:
            self.errors.append(f"OCR Error: {str(e)}")
            if debug:
                import traceback
                st.error(f"OCR failed: {str(e)}")
                st.code(traceback.format_exc())
        
        doc.close()

# Report generator
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
    st.markdown("**Using Image Analysis to Extract Performance Symbols**")
    
    st.warning("""
    **⚠️ Experimental OCR Version**
    
    This version attempts to detect checkmark symbols using image analysis.
    - Converts PDF pages to images
    - Analyzes pixel patterns where symbols should appear
    - May require manual verification
    
    **Enable Debug Mode** to see detailed processing information.
    """)
    
    st.markdown("---")

    with st.sidebar:
        st.header("⚙️ Settings")
        school_name = st.text_input("School Name:", placeholder="Your school")
        logo_file = st.file_uploader("School Logo:", type=["png", "jpg", "jpeg"])
        
        st.markdown("---")
        st.markdown("### 🐛 Debug")
        debug_mode = st.checkbox("Enable Debug Mode", value=True, 
                                 help="Shows detailed processing steps")
        st.session_state['debug_mode'] = debug_mode

        st.markdown("---")
        st.markdown("### 📖 About")
        st.markdown("OCR-based ILEARN report analyzer")

    uploaded_files = st.file_uploader("📁 Upload ILEARN PDF Reports", type="pdf", accept_multiple_files=True)

    if not uploaded_files:
        st.info("👆 Upload PDF files to begin")
        st.stop()

    with st.spinner("Processing PDFs with OCR (may take 1-2 minutes)..."):
        parser = ILEARNOCRParser()
        parser.parse_files(uploaded_files)

    if parser.errors:
        with st.expander("⚠️ Processing Warnings"):
            for error in parser.errors:
                st.warning(error)

    if not parser.student_data:
        st.error("No student data found")
        st.stop()

    # Check if we got any performance data
    has_performance_data = any(
        sum(counts['correct'] + counts['incorrect'] + counts['partial'] 
            for counts in info['standards'].values()) > 0
        for info in parser.student_data.values()
    )

    if not has_performance_data:
        st.warning("""
        **Symbol Detection Failed**
        
        The OCR system could not detect performance symbols in your PDFs.
        This could be due to:
        - PDF formatting differences
        - Symbol rendering method
        - Image resolution issues
        
        **Student information WAS extracted:**
        """)
        
        for student, info in parser.student_data.items():
            st.write(f"- **{student}**: Lexile {info['lexile']}L, {info['proficiency']}")
        
        st.info("""
        **Recommendations:**
        1. Contact Cambium Assessment for machine-readable data
        2. Use their online portal's export feature
        3. Try adjusting DPI settings in the code (line 132: dpi=150)
        """)
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
    st.success("✅ Symbol detection successful!")
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

    if data:
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
                        if total > 0:
                            success = (counts['correct'] / total * 100)
                            student_rows.append({
                                'Standard': standard,
                                'Correct': counts['correct'],
                                'Partial': counts['partial'],
                                'Incorrect': counts['incorrect'],
                                'Success Rate': f"{success:.1f}%"
                            })

                    if student_rows:
                        st.dataframe(pd.DataFrame(student_rows), use_container_width=True, hide_index=True)

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
