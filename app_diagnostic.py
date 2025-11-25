import streamlit as st
import fitz  # PyMuPDF
import re
from collections import defaultdict

st.set_page_config(page_title="ILEARN Symbol Diagnostic", layout="wide")

st.title("🔍 ILEARN PDF Symbol Diagnostic Tool")
st.write("Upload your ILEARN PDF to see detailed information about the vector graphics (symbols)")

uploaded_file = st.file_uploader("Upload ILEARN PDF", type=['pdf'])

if uploaded_file:
    # Save uploaded file temporarily
    with open("/tmp/diagnostic.pdf", "wb") as f:
        f.write(uploaded_file.read())
    
    doc = fitz.open("/tmp/diagnostic.pdf")
    
    st.success(f"✅ Loaded PDF with {len(doc)} pages")
    
    # Let user select a page to analyze
    page_num = st.selectbox("Select page to analyze:", range(len(doc)), format_func=lambda x: f"Page {x+1}")
    
    page = doc[page_num]
    
    st.subheader(f"Page {page_num + 1} Analysis")
    
    # Extract text to find standards
    blocks = page.get_text("dict")["blocks"]
    
    # Find standards on this page
    standards_found = []
    for block in blocks:
        if "lines" in block:
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"]
                    if re.search(r'RC\|5\.RC\.\d+', text):
                        bbox = span["bbox"]
                        standard_match = re.search(r'(RC\|5\.RC\.\d+)', text)
                        if standard_match:
                            standards_found.append({
                                'standard': standard_match.group(1),
                                'y0': bbox[1],
                                'y1': bbox[3],
                                'x0': bbox[0],
                                'x1': bbox[2]
                            })
    
    st.write(f"**Found {len(standards_found)} standards on this page:**")
    for std in standards_found[:5]:  # Show first 5
        st.write(f"- {std['standard']} at Y={std['y0']:.1f}")
    
    # Get all drawings
    drawings = page.get_drawings()
    
    st.write(f"**Found {len(drawings)} vector drawings on this page**")
    
    # Analyze drawings
    if drawings:
        st.subheader("Drawing Details")
        
        # Show detailed info for each drawing
        for i, drawing in enumerate(drawings[:20]):  # Limit to first 20
            with st.expander(f"Drawing #{i+1}"):
                st.write("**Position:**")
                rect = drawing.get('rect', None)
                if rect:
                    st.write(f"- X: {rect.x0:.1f} to {rect.x1:.1f}")
                    st.write(f"- Y: {rect.y0:.1f} to {rect.y1:.1f}")
                    st.write(f"- Width: {rect.x1 - rect.x0:.1f}")
                    st.write(f"- Height: {rect.y1 - rect.y0:.1f}")
                
                st.write("**Colors:**")
                st.write(f"- Fill: {drawing.get('fill', None)}")
                st.write(f"- Stroke: {drawing.get('color', None)}")
                st.write(f"- Width: {drawing.get('width', 0)}")
                
                items = drawing.get('items', [])
                st.write(f"**Path Commands ({len(items)} total):**")
                
                # Count command types
                cmd_counts = defaultdict(int)
                for item in items:
                    cmd_counts[item[0]] += 1
                
                for cmd, count in cmd_counts.items():
                    cmd_name = {
                        'l': 'line',
                        'c': 'curve',
                        're': 'rectangle',
                        'm': 'move',
                        'qu': 'quad curve'
                    }.get(cmd, cmd)
                    st.write(f"- {cmd_name}: {count}")
                
                # Show first few commands
                st.write("**First few commands:**")
                for item in items[:5]:
                    st.code(str(item))
                
                # Try to match this drawing to a standard
                if rect and standards_found:
                    st.write("**Possible matches:**")
                    for std in standards_found:
                        if abs(rect.y0 - std['y0']) < 20:
                            st.write(f"✓ Near standard {std['standard']} (ΔY = {abs(rect.y0 - std['y0']):.1f})")
        
        # Summary statistics
        st.subheader("Summary Statistics")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            # Group by command pattern
            patterns = []
            for drawing in drawings:
                items = drawing.get('items', [])
                cmd_counts = defaultdict(int)
                for item in items:
                    cmd_counts[item[0]] += 1
                pattern = tuple(sorted(cmd_counts.items()))
                patterns.append(pattern)
            
            st.write("**Command Patterns:**")
            pattern_counts = defaultdict(int)
            for p in patterns:
                pattern_counts[p] += 1
            
            for pattern, count in sorted(pattern_counts.items(), key=lambda x: -x[1])[:5]:
                pattern_str = ", ".join([f"{k}={v}" for k, v in pattern])
                st.write(f"- {pattern_str}: {count}x")
        
        with col2:
            # Group by fill/stroke
            fill_stroke = []
            for drawing in drawings:
                has_fill = bool(drawing.get('fill', None))
                has_stroke = bool(drawing.get('color', None))
                fill_stroke.append((has_fill, has_stroke))
            
            st.write("**Fill/Stroke:**")
            fs_counts = defaultdict(int)
            for fs in fill_stroke:
                fs_counts[fs] += 1
            
            for (has_fill, has_stroke), count in fs_counts.items():
                label = []
                if has_fill:
                    label.append("Filled")
                if has_stroke:
                    label.append("Stroked")
                if not label:
                    label.append("None")
                st.write(f"- {' + '.join(label)}: {count}x")
        
        with col3:
            # Group by size
            st.write("**Sizes:**")
            sizes = []
            for drawing in drawings:
                rect = drawing.get('rect', None)
                if rect:
                    width = rect.x1 - rect.x0
                    height = rect.y1 - rect.y0
                    sizes.append((width, height))
            
            if sizes:
                avg_width = sum(s[0] for s in sizes) / len(sizes)
                avg_height = sum(s[1] for s in sizes) / len(sizes)
                st.write(f"- Avg Width: {avg_width:.1f}")
                st.write(f"- Avg Height: {avg_height:.1f}")
                st.write(f"- Min Width: {min(s[0] for s in sizes):.1f}")
                st.write(f"- Max Width: {max(s[0] for s in sizes):.1f}")
    
    doc.close()

else:
    st.info("👆 Upload a PDF file to begin analysis")
    st.write("""
    This tool will show you:
    - All standards found on each page
    - All vector drawings (symbols) and their properties
    - Which drawings are near which standards
    - Pattern analysis to help identify checkmarks vs X's vs circles
    """)
