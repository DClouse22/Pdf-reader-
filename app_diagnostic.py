import streamlit as st
import fitz  # PyMuPDF
import re
from collections import defaultdict

st.set_page_config(page_title="ILEARN Text Analysis", layout="wide")

st.title("📝 ILEARN PDF Text Character Analysis")
st.write("Check if symbols are text characters or images")

uploaded_file = st.file_uploader("Upload ILEARN PDF", type=['pdf'])

if uploaded_file:
    with open("/tmp/diagnostic.pdf", "wb") as f:
        f.write(uploaded_file.read())
    
    doc = fitz.open("/tmp/diagnostic.pdf")
    
    st.success(f"✅ Loaded PDF with {len(doc)} pages")
    
    page_num = st.selectbox("Select page:", range(len(doc)), format_func=lambda x: f"Page {x+1}")
    page = doc[page_num]
    
    st.subheader(f"Page {page_num + 1} - Character Analysis")
    
    # Get detailed text with font information
    blocks = page.get_text("dict")["blocks"]
    
    # Find all unique characters and their fonts
    char_fonts = defaultdict(set)
    font_chars = defaultdict(set)
    all_chars = set()
    
    # Also track characters in the rightmost column (where symbols should be)
    right_column_chars = []
    
    for block in blocks:
        if "lines" in block:
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span["text"]
                    font = span["font"]
                    bbox = span["bbox"]
                    x_pos = bbox[0]
                    
                    # Track all characters
                    for char in text:
                        all_chars.add(char)
                        char_fonts[char].add(font)
                        font_chars[font].add(char)
                    
                    # Track characters on the right side (X > 500)
                    if x_pos > 500:
                        for char in text:
                            right_column_chars.append({
                                'char': char,
                                'font': font,
                                'x': x_pos,
                                'y': bbox[1],
                                'text': text
                            })
    
    # Display findings
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Right Column Characters")
        st.write(f"Found {len(right_column_chars)} characters with X > 500")
        
        if right_column_chars:
            # Group by character
            char_counts = defaultdict(int)
            for item in right_column_chars:
                char_counts[item['char']] += 1
            
            st.write("**Character frequency:**")
            for char, count in sorted(char_counts.items(), key=lambda x: -x[1]):
                # Show character, its unicode, and count
                try:
                    unicode_name = f"U+{ord(char):04X}"
                except:
                    unicode_name = "?"
                
                # Display the character safely
                if ord(char) < 32 or ord(char) == 127:
                    display = f"[control char]"
                else:
                    display = char
                
                st.write(f"- '{display}' ({unicode_name}): {count}x")
            
            # Show sample entries
            st.write("**Sample entries:**")
            for item in right_column_chars[:20]:
                st.code(f"'{item['char']}' in font '{item['font']}' at ({item['x']:.1f}, {item['y']:.1f}) - full text: '{item['text']}'")
    
    with col2:
        st.subheader("All Fonts Used")
        st.write(f"Found {len(font_chars)} different fonts")
        
        for font in sorted(font_chars.keys()):
            chars = font_chars[font]
            # Show first 50 characters
            char_sample = ''.join(sorted(chars)[:50])
            st.write(f"**{font}:**")
            st.code(char_sample)
            st.write(f"({len(chars)} unique characters)")
            st.write("---")
    
    # Look for special unicode symbols
    st.subheader("Special Symbols Detected")
    
    special_symbols = {
        '✓': 'Check mark',
        '✔': 'Heavy check mark',
        '✗': 'Ballot X',
        '✘': 'Heavy ballot X',
        '×': 'Multiplication sign',
        '⊖': 'Circled minus',
        '◯': 'White circle',
        '○': 'White circle (alt)',
        '●': 'Black circle',
        '•': 'Bullet'
    }
    
    found_symbols = []
    for char in all_chars:
        if char in special_symbols:
            fonts = ', '.join(char_fonts[char])
            found_symbols.append(f"- {char} ({special_symbols[char]}) in fonts: {fonts}")
    
    if found_symbols:
        st.success("Found special symbols:")
        for s in found_symbols:
            st.write(s)
    else:
        st.warning("No standard unicode symbols found. Symbols might be in a custom font encoding.")
    
    # Check for images
    st.subheader("Images on Page")
    images = page.get_images()
    if images:
        st.write(f"Found {len(images)} images")
        for img in images[:5]:
            st.write(f"- Image: xref={img[0]}, size={img[2]}x{img[3]}")
    else:
        st.info("No images found")
    
    doc.close()

else:
    st.info("👆 Upload a PDF to analyze text characters")
