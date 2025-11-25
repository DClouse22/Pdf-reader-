import streamlit as st
import fitz  # PyMuPDF
import pandas as pd
import re
from collections import defaultdict
from io import BytesIO
from PIL import Image
import io

st.set_page_config(page_title="ILEARN Analytics Tool", layout="wide")

# Custom CSS
st.markdown("""
    <style>
    .main { padding: 2rem; }
    .stTabs [data-baseweb="tab-list"] { gap: 2rem; }
    </style>
""", unsafe_allow_html=True)

class ILEARNParser:
    def __init__(self):
        self.standards_summary = defaultdict(lambda: {'correct': 0, 'incorrect': 0, 'partial': 0})
        self.student_data = {}
        self.errors = []
    
    def parse_pdf(self, pdf_file):
        """Main parsing function"""
        doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        current_student = None
        
        for page_num in range(len(doc)):
            progress_bar.progress((page_num + 1) / len(doc))
            status_text.text(f"Processing page {page_num + 1} of {len(doc)}...")
            
            page = doc[page_num]
            
            # Check for new student on this page
            student_info = self._extract_student_info(page.get_text())
            
            if student_info['name']:
                current_student = student_info['name']
                
                if current_student not in self.student_data:
                    self.student_data[current_student] = {
                        'lexile_range': student_info['lexile'],
                        'performance_level': student_info['performance'],
                        'standards': defaultdict(lambda: {'correct': 0, 'incorrect': 0, 'partial': 0})
                    }
            
            # Extract standards with image-based symbol detection
            if current_student:
                self._extract_standards_with_images(page, current_student)
        
        progress_bar.empty()
        status_text.empty()
        doc.close()
        
        if self.student_data:
            student_names = ', '.join(list(self.student_data.keys())[:5])
            if len(self.student_data) > 5:
                student_names += f" and {len(self.student_data) - 5} more"
            self.errors.append(f"✅ Found {len(self.student_data)} students: {student_names}")
    
    def _extract_student_info(self, text):
        """Extract student name, Lexile, and performance level"""
        name_match = re.search(r'Name:\s*([A-Z][a-z]+)\s+([A-Z][a-z]+)', text)
        lexile_match = re.search(r'Lexile.*?(\d+L)\s*-\s*(\d+L)', text)
        perf_match = re.search(r'Performance Level:\s*(At Proficiency|Above Proficiency|Approaching Proficiency|Below Proficiency)', text)
        
        return {
            'name': f"{name_match.group(1)} {name_match.group(2)}" if name_match else None,
            'lexile': f"{lexile_match.group(1)}-{lexile_match.group(2)}" if lexile_match else None,
            'performance': perf_match.group(1) if perf_match else None
        }
    
    def _extract_standards_with_images(self, page, student_name):
        """Extract standards by detecting small images (symbols) in the right column"""
        
        # Get text blocks to find standards and their positions
        blocks = page.get_text("dict")["blocks"]
        
        # Find standards with their Y positions
        standard_positions = []
        for block in blocks:
            if "lines" in block:
                for line in block["lines"]:
                    for span in line["spans"]:
                        text = span["text"]
                        if re.search(r'RC\|5\.RC\.\d+', text):
                            bbox = span["bbox"]
                            standard_match = re.search(r'(RC\|5\.RC\.\d+)', text)
                            if standard_match:
                                standard_positions.append({
                                    'standard': standard_match.group(1),
                                    'y_min': bbox[1],
                                    'y_max': bbox[3],
                                    'y_center': (bbox[1] + bbox[3]) / 2
                                })
        
        # Get all images on the page
        image_list = page.get_images(full=True)
        
        # Track which images are symbols (small images in right column)
        symbol_images = []
        
        for img_index, img in enumerate(image_list):
            xref = img[0]
            
            # Get image position on page
            img_rects = page.get_image_rects(xref)
            
            for rect in img_rects:
                x = rect.x0
                y = rect.y0
                width = rect.x1 - rect.x0
                height = rect.y1 - rect.y0
                
                # Symbols should be:
                # 1. Small (typically 10-30 pixels)
                # 2. In the right column (X > 450)
                # 3. Square-ish (aspect ratio close to 1:1)
                
                if width < 50 and height < 50 and x > 450:
                    aspect_ratio = width / height if height > 0 else 0
                    
                    if 0.5 < aspect_ratio < 2.0:  # Roughly square
                        # Extract the image to analyze it
                        try:
                            base_image = page.parent.extract_image(xref)
                            image_bytes = base_image["image"]
                            
                            # Open with PIL to analyze
                            pil_image = Image.open(io.BytesIO(image_bytes))
                            
                            # Analyze the image to determine symbol type
                            symbol_type = self._classify_symbol_image(pil_image)
                            
                            symbol_images.append({
                                'y': y,
                                'y_center': y + height/2,
                                'type': symbol_type,
                                'size': (width, height)
                            })
                        except Exception as e:
                            pass
        
        # Match symbols to standards based on Y position
        symbols_found = 0
        standards_found = len(standard_positions)
        
        for std_pos in standard_positions:
            standard = std_pos['standard']
            std_y = std_pos['y_center']
            
            # Find closest symbol (within ±30 pixels)
            closest_symbol = None
            min_distance = 30
            
            for symbol in symbol_images:
                distance = abs(symbol['y_center'] - std_y)
                if distance < min_distance:
                    min_distance = distance
                    closest_symbol = symbol
            
            if closest_symbol:
                symbol_type = closest_symbol['type']
                self.standards_summary[standard][symbol_type] += 1
                self.student_data[student_name]['standards'][standard][symbol_type] += 1
                symbols_found += 1
        
        if standards_found > 0:
            self.errors.append(
                f"📊 {student_name}: {standards_found} standards, {symbols_found} symbols matched"
            )
    
    def _classify_symbol_image(self, pil_image):
        """Analyze image pixels to determine if it's a checkmark, X, or circle"""
        
        # Convert to RGB if needed
        if pil_image.mode != 'RGB':
            pil_image = pil_image.convert('RGB')
        
        # Resize to standard size for analysis
        pil_image = pil_image.resize((20, 20), Image.Resampling.LANCZOS)
        
        # Get pixel data
        pixels = list(pil_image.getdata())
        
        # Count dark pixels (symbols are typically dark/black)
        dark_pixels = sum(1 for r, g, b in pixels if (r + g + b) / 3 < 128)
        total_pixels = len(pixels)
        
        if dark_pixels == 0:
            return 'partial'  # Empty or very light - assume partial
        
        # Analyze shape by checking pixel distribution
        # This is a simplified heuristic - you might need to adjust
        
        # Get the center region and corners
        center_pixels = [pixels[i] for i in [210, 211, 190, 191]]  # Rough center
        corner_pixels = [pixels[0], pixels[19], pixels[380], pixels[399]]  # Corners
        
        center_dark = sum(1 for r, g, b in center_pixels if (r + g + b) / 3 < 128)
        corner_dark = sum(1 for r, g, b in corner_pixels if (r + g + b) / 3 < 128)
        
        # Checkmark: darker in center/bottom, lighter in top corners
        # X: darker in all corners
        # Circle: darker around edges, lighter in center
        
        dark_ratio = dark_pixels / total_pixels
        
        if dark_ratio < 0.2:
            return 'partial'  # Very sparse - circle/partial
        elif corner_dark >= 3:
            return 'incorrect'  # Dark corners = X
        else:
            return 'correct'  # Otherwise assume checkmark
    
    def get_dataframe(self):
        """Convert data to DataFrame"""
        rows = []
        for standard, counts in self.standards_summary.items():
            total = counts['correct'] + counts['incorrect'] + counts['partial']
            if total > 0:
                success_rate = (counts['correct'] + 0.5 * counts['partial']) / total
                rows.append({
                    'Standard': standard,
                    'Correct': counts['correct'],
                    'Incorrect': counts['incorrect'],
                    'Partial': counts['partial'],
                    'Total': total,
                    'Success Rate': f"{success_rate:.1%}",
                    'Success Rate Value': success_rate
                })
        return pd.DataFrame(rows)

# Streamlit UI
st.title("📊 ILEARN Analytics Tool")
st.write("Upload ILEARN PDF reports to analyze student performance across academic standards")

uploaded_files = st.file_uploader(
    "Upload PDF file(s)", 
    type=['pdf'], 
    accept_multiple_files=True,
    help="Select one or more ILEARN PDF reports"
)

if uploaded_files:
    parser = ILEARNParser()
    
    with st.spinner("Processing PDFs..."):
        for uploaded_file in uploaded_files:
            parser.parse_pdf(uploaded_file)
    
    # Show debug/error messages
    if parser.errors:
        with st.expander("📋 Processing Log", expanded=False):
            for error in parser.errors:
                st.write(error)
    
    df = parser.get_dataframe()
    
    if df.empty or 'Success Rate Value' not in df.columns:
        st.error("❌ No standards data found in the PDF. Please check the file format.")
        st.stop()
    
    # Display data
    st.subheader("📈 Standards Performance Overview")
    
    # Sort by success rate
    df_display = df.sort_values('Success Rate Value', ascending=False)
    
    # Color code the dataframe
    def color_success_rate(val):
        if isinstance(val, str) and '%' in val:
            num = float(val.strip('%'))
            if num >= 80:
                return 'background-color: #d4edda'
            elif num >= 60:
                return 'background-color: #fff3cd'
            else:
                return 'background-color: #f8d7da'
        return ''
    
    st.dataframe(
        df_display.style.applymap(color_success_rate, subset=['Success Rate']),
        use_container_width=True,
        hide_index=True
    )
    
    # Export options
    st.download_button(
        label="📥 Download CSV",
        data=df.to_csv(index=False),
        file_name="ilearn_analysis.csv",
        mime="text/csv"
    )

else:
    st.info("👆 Upload one or more PDF files to begin analysis")
    st.write("""
    ### Features:
    - Extract student performance data from ILEARN PDFs
    - Analyze performance across academic standards
    - Track correct, incorrect, and partial credit responses
    - Export results to CSV
    """)
