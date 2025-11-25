
import streamlit as st
import fitz
import re
import pandas as pd
from collections import defaultdict
from datetime import datetime
from pdf2image import convert_from_bytes
from PIL import Image
import numpy as np
import pytesseract

st.set_page_config(page_title="ILEARN Analytics Tool - OCR", page_icon="📊", layout="wide")

# --- Improved Symbol Detector ---
class SymbolDetector:
    def detect_symbol_in_region(self, image, x, y, w, h, debug=False):
        """Detect ✓, X, or O using OCR fallback"""
        try:
            region = image.crop((x, y, x+w, y+h))
            # OCR detection
            ocr_text = pytesseract.image_to_string(region, config="--psm 8")
            ocr_text = ocr_text.strip()
            if debug:
                st.write(f"OCR detected: '{ocr_text}'")
                st.image(region, caption=f"Crop region ({x},{y})")

            if "✓" in ocr_text or "v" in ocr_text:
                return 'correct'
            elif "X" in ocr_text or "x" in ocr_text:
                return 'incorrect'
            elif "O" in ocr_text or "o" in ocr_text:
                return 'partial'

            # Fallback: pixel analysis
            region_gray = region.convert('L')
            pixels = np.array(region_gray)
            dark_ratio = np.sum(pixels < 200) / pixels.size
            if dark_ratio > 0.25:
                return 'incorrect'
            elif dark_ratio > 0.12:
                return 'correct'
            elif dark_ratio > 0.05:
                return 'partial'
            return None
        except Exception as e:
            if debug:
                st.error(f"Symbol detection error: {e}")
            return None

# --- Parser ---
class ILEARNOCRParser:
    def __init__(self):
        self.student_data = defaultdict(lambda: {
            'name': '', 'lexile': 0, 'proficiency': '',
            'standards': defaultdict(lambda: {'correct': 0, 'incorrect': 0, 'partial': 0})
        })
        self.standards_summary = defaultdict(lambda: {'correct': 0, 'incorrect': 0, 'partial': 0, 'total_tests': 0})
        self.errors = []
        self.detector = SymbolDetector()

    def parse_files(self, uploaded_files):
        for uploaded_file in uploaded_files:
            try:
                self._parse_single_file(uploaded_file)
            except Exception as e:
                self.errors.append(str(e))
        return self

    def _parse_single_file(self, uploaded_file):
        debug = st.session_state.get('debug_mode', False)
        pdf_bytes = uploaded_file.read()
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        current_student = None

        # Extract student info
        for page in doc:
            text = page.get_text()
            for line in text.split("\n"):
                if line.strip().startswith("Name:"):
                    current_student = line.split("Name:")[-1].strip()
                    self.student_data[current_student]['name'] = current_student
                if current_student and "Lexile" in line:
                    match = re.search(r'(\d+)L', line)
                    if match:
                        self.student_data[current_student]['lexile'] = int(match.group(1))
                if current_student and line.strip().startswith("Performance Level:"):
                    self.student_data[current_student]['proficiency'] = line.split(":")[-1].strip()

        if not current_student:
            self.errors.append("Student name not found")
            return

        # Convert to image for symbol detection
        images = convert_from_bytes(pdf_bytes, dpi=300)
        for page_num, image in enumerate(images):
            page = doc[page_num]
            text = page.get_text()
            if 'Student Performance*' not in text:
                continue

            blocks = page.get_text("dict")["blocks"]
            perf_col_x = None
            for block in blocks:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        if "Performance*" in span["text"]:
                            perf_col_x = span["bbox"][2]
                            break
            if not perf_col_x:
                continue

            page_width, page_height = page.rect.width, page.rect.height
            img_width, img_height = image.size
            scale_x, scale_y = img_width / page_width, img_height / page_height

            standards = re.findall(r'(RC\\d+\\.RC\\.\\d+)', text)
            for block in blocks:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        for standard in standards:
                            if standard in span["text"]:
                                std_y = span["bbox"][1]
                                symbol_x = int(perf_col_x * scale_x) + 10
                                symbol_y = int(std_y * scale_y) - 10
                                symbol_w, symbol_h = 80, 80
                                symbol_x = max(0, min(symbol_x, img_width - symbol_w))
                                symbol_y = max(0, min(symbol_y, img_height - symbol_h))

                                symbol_type = self.detector.detect_symbol_in_region(image, symbol_x, symbol_y, symbol_w, symbol_h, debug)
                                if symbol_type:
                                    self.student_data[current_student]['standards'][standard][symbol_type] += 1
                                    self.standards_summary[standard][symbol_type] += 1
                                    self.standards_summary[standard]['total_tests'] += 1

        doc.close()

# --- Streamlit UI ---
st.title("📊 ILEARN Analytics Tool - OCR Version")
st.sidebar.header("⚙️ Settings")
debug_mode = st.sidebar.checkbox("Enable Debug Mode", value=False)
st.session_state['debug_mode'] = debug_mode
uploaded_files = st.file_uploader("📂 Upload ILEARN PDF Reports", type="pdf", accept_multiple_files=True)

if uploaded_files:
    parser = ILEARNOCRParser().parse_files(uploaded_files)
    if parser.errors:
        st.warning("Errors occurred:")
        for e in parser.errors:
            st.write(e)

    st.write(parser.student_data)
    st.write(parser.standards_summary)
else:
    st.info("Upload PDF files to start")
