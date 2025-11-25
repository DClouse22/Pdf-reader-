import streamlit as st
import fitz
import re
import pandas as pd
from collections import defaultdict
from fpdf import FPDF
import io
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

# ===============================================================================
# PAGE CONFIGURATION
# ===============================================================================
st.set_page_config(
    page_title="ILEARN Analytics Tool",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ===============================================================================
# CUSTOM CSS FOR BETTER STYLING
# ===============================================================================
st.markdown("""
    <style>
    .main > div {padding-top: 2rem;}
    .stMetric {background-color: #f0f2f6; padding: 15px; border-radius: 10px;}
    .stExpander {border: 1px solid #e0e0e0; border-radius: 5px;}
    h1 {color: #1f77b4;}
    h2 {color: #2c3e50;}
    .warning-box {background-color: #fff3cd; padding: 10px; border-radius: 5px; border-left: 4px solid #ffc107;}
    .success-box {background-color: #d4edda; padding: 10px; border-radius: 5px; border-left: 4px solid #28a745;}
    </style>
""", unsafe_allow_html=True)

# ===============================================================================
# DATA PARSER CLASS
# ===============================================================================
class ILEARNParser:
    """Handles parsing of ILEARN PDF reports with improved error handling"""
    
    def __init__(self):
        self.standards_items = defaultdict(set)
        self.standards_counts = defaultdict(lambda: {"Full Credit": 0, "Partial Credit": 0, "No Credit": 0})
        self.student_data = defaultdict(lambda: defaultdict(lambda: {"Full Credit": 0, "Partial Credit": 0, "No Credit": 0}))
        self.student_names = []
        self.lexile_values = []
        self.proficiency_levels = []
        self.student_lexile_map = {}
        self.student_proficiency_map = {}
        self.standard_pattern = re.compile(r"RC\\n5\.RC\.\d+")
        self.errors = []
        
    def parse_files(self, uploaded_files):
        """Parse multiple PDF files and extract ILEARN data"""
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        for idx, uploaded_file in enumerate(uploaded_files):
            status_text.text(f"Processing {uploaded_file.name}...")
            try:
                self._parse_single_file(uploaded_file)
            except Exception as e:
                error_msg = f"Error processing {uploaded_file.name}: {str(e)}"
                self.errors.append(error_msg)
                st.warning(error_msg)
            
            progress_bar.progress((idx + 1) / len(uploaded_files))
        
        status_text.text("✅ Processing complete!")
        return self
    
    def _parse_single_file(self, uploaded_file):
        """Parse a single PDF file"""
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        current_student = None
        
        for page in doc:
            text = page.get_text()
            lines = text.split("\n")
            current_standard = None
            
            for line in lines:
                # Extract student name
                if line.startswith("Name:"):
                    current_student = line.replace("Name:", "").strip()
                    if current_student and current_student not in self.student_names:
                        self.student_names.append(current_student)
                
                # Extract Lexile score
                if "Lexile" in line and current_student:
                    lex_match = re.search(r"(\d+)L", line)
                    if lex_match:
                        lexile = int(lex_match.group(1))
                        self.lexile_values.append(lexile)
                        self.student_lexile_map[current_student] = lexile
                
                # Extract proficiency level
                if "Performance Level:" in line and current_student:
                    prof_level = line.split(":")[-1].strip()
                    self.proficiency_levels.append(prof_level)
                    self.student_proficiency_map[current_student] = prof_level
                
                # Extract academic standards
                match = self.standard_pattern.search(line)
                if match:
                    current_standard = match.group()
                    self.standards_items[current_standard].add(line.strip())
                
                # Track performance on standards
                if current_standard and current_student:
                    if "✓" in line or "v" in line:
                        self.standards_counts[current_standard]["Full Credit"] += 1
                        self.student_data[current_student][current_standard]["Full Credit"] += 1
                    elif "O" in line:
                        self.standards_counts[current_standard]["Partial Credit"] += 1
                        self.student_data[current_student][current_standard]["Partial Credit"] += 1
                    elif "X" in line:
                        self.standards_counts[current_standard]["No Credit"] += 1
                        self.student_data[current_student][current_standard]["No Credit"] += 1
        
        doc.close()

# ===============================================================================
# REPORT GENERATOR CLASS
# ===============================================================================
class ReportGenerator:
    """Generates PDF reports with school branding"""
    
    def __init__(self, school_name="", logo_file=None):
        self.school_name = school_name
        self.logo_file = logo_file
    
    def create_pdf(self, df, metrics):
        """Create a comprehensive PDF report"""
        pdf = FPDF()
        pdf.add_page()
        
        # Add logo if provided
        if self.logo_file:
            try:
                img_buffer = io.BytesIO(self.logo_file.getvalue())
                pdf.image(img_buffer, x=10, y=8, w=30)
            except:
                pass
        
        # Title
        pdf.set_font("Arial", "B", 18)
        pdf.cell(0, 10, "ILEARN Analytics Report", ln=True, align="C")
        
        # School name
        if self.school_name:
            pdf.set_font("Arial", "I", 14)
            pdf.cell(0, 8, self.school_name, ln=True, align="C")
        
        # Metadata
        pdf.set_font("Arial", "", 10)
        pdf.cell(0, 6, f"Generated: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", ln=True, align="C")
        pdf.ln(10)
        
        # Executive Summary
        pdf.set_font("Arial", "B", 14)
        pdf.cell(0, 10, "Executive Summary", ln=True)
        pdf.set_font("Arial", "", 11)
        pdf.multi_cell(0, 6, f"Total Students: {metrics['total_students']}\n"
                             f"At/Above Proficiency: {metrics['at_above_pct']:.1f}%\n"
                             f"Needs Support: {metrics['needs_support_pct']:.1f}%\n"
                             f"Average Lexile Level: {metrics['avg_lexile']}L")
        pdf.ln(8)
        
        # Standards Performance
        pdf.set_font("Arial", "B", 14)
        pdf.cell(0, 10, "Academic Standards Performance", ln=True)
        pdf.set_font("Arial", "B", 9)
        pdf.cell(45, 8, "Standard", 1)
        pdf.cell(25, 8, "Full Credit", 1)
        pdf.cell(30, 8, "Partial Credit", 1)
        pdf.cell(25, 8, "No Credit", 1)
        pdf.cell(30, 8, "Success Rate", 1, ln=True)
        
        pdf.set_font("Arial", "", 8)
        for _, row in df.iterrows():
            pdf.cell(45, 7, str(row['Academic Standard']), 1)
            pdf.cell(25, 7, str(row['Full Credit (✓)']), 1, align="C")
            pdf.cell(30, 7, str(row['Partial Credit (O)']), 1, align="C")
            pdf.cell(25, 7, str(row['No Credit (X)']), 1, align="C")
            pdf.cell(30, 7, str(row['Success Rate']), 1, align="C", ln=True)
        
        return pdf.output(dest="S").encode("latin-1")

# ===============================================================================
# MAIN APPLICATION
# ===============================================================================
def main():
    # Header
    st.title("📊 ILEARN Analytics Tool")
    st.markdown("**Advanced PDF parsing with interactive visualizations and comprehensive reporting**")
    st.markdown("---")
    
    # Sidebar configuration
    with st.sidebar:
        st.header("⚙️ Settings")
        school_name = st.text_input("School Name:", placeholder="Enter your school name")
        logo_file = st.file_uploader("School Logo:", type=["png", "jpg", "jpeg"])
        
        st.markdown("---")
        st.markdown("### 📖 Instructions")
        st.markdown("""
        1. Upload one or more ILEARN PDF reports
        2. Review class-wide metrics and performance
        3. Filter and analyze individual students
        4. Export data as CSV or PDF reports
        """)
        
        st.markdown("---")
        st.markdown("### ℹ️ About")
        st.markdown("Version 4.0 | Enhanced Analytics")
    
    # File upload
    uploaded_files = st.file_uploader(
        "📁 Upload ILEARN PDF Reports",
        type="pdf",
        accept_multiple_files=True,
        help="You can upload multiple PDF files at once"
    )
    
    if not uploaded_files:
        st.info("👆 Please upload at least one PDF file to begin analysis")
        st.stop()
    
    # Parse uploaded files
    with st.spinner("Processing PDF files..."):
        parser = ILEARNParser()
        parser.parse_files(uploaded_files)
    
    # Display any errors
    if parser.errors:
        with st.expander("⚠️ Processing Warnings", expanded=False):
            for error in parser.errors:
                st.warning(error)
    
    # Check if data was extracted
    if not parser.student_names:
        st.error("No student data found in uploaded files. Please verify the PDF format.")
        st.stop()
    
    # Calculate metrics
    total_students = len(set(parser.student_names))
    avg_lexile = int(sum(parser.lexile_values) / len(parser.lexile_values)) if parser.lexile_values else 0
    at_above = sum(1 for level in parser.proficiency_levels if "At" in level or "Above" in level)
    needs_support = total_students - at_above
    at_above_pct = (at_above / total_students) * 100 if total_students else 0
    needs_support_pct = (needs_support / total_students) * 100 if total_students else 0
    
    metrics = {
        'total_students': total_students,
        'avg_lexile': avg_lexile,
        'at_above': at_above,
        'needs_support': needs_support,
        'at_above_pct': at_above_pct,
        'needs_support_pct': needs_support_pct
    }
    
    # Dashboard Metrics
    st.subheader("📈 Class Overview Dashboard")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Students", total_students, help="Number of students analyzed")
    with col2:
        st.metric("At/Above Proficiency", f"{at_above_pct:.1f}%", 
                 delta=f"{at_above} students",
                 help="Percentage of students performing at or above grade level")
    with col3:
        st.metric("Needs Support", f"{needs_support_pct:.1f}%",
                 delta=f"{needs_support} students",
                 delta_color="inverse",
                 help="Percentage of students needing additional support")
    with col4:
        st.metric("Average Lexile", f"{avg_lexile}L",
                 help="Class average Lexile reading level")
    
    st.markdown("---")
    
    # Prepare class overview data
    data = []
    for standard in parser.standards_items:
        unique_items = len(parser.standards_items[standard])
        full_credit = parser.standards_counts[standard]["Full Credit"]
        partial_credit = parser.standards_counts[standard]["Partial Credit"]
        no_credit = parser.standards_counts[standard]["No Credit"]
        total_attempts = full_credit + partial_credit + no_credit
        success_rate = (full_credit / total_attempts * 100) if total_attempts > 0 else 0
        
        data.append({
            "Academic Standard": standard,
            "Students": total_students,
            "Total Tests": unique_items,
            "Full Credit (✓)": full_credit,
            "Partial Credit (O)": partial_credit,
            "No Credit (X)": no_credit,
            "Success Rate": f"{success_rate:.1f}%",
            "Success Rate Value": success_rate
        })
    
    df = pd.DataFrame(data)
    df = df.sort_values("Success Rate Value", ascending=False)
    
    # Class Performance Section
    st.subheader("📚 Academic Standards Performance")
    
    # Create tabs for different views
    tab1, tab2, tab3 = st.tabs(["📊 Overview Table", "📈 Success Rate Chart", "🎯 Detailed Analysis"])
    
    with tab1:
        st.dataframe(
            df.drop('Success Rate Value', axis=1),
            use_container_width=True,
            hide_index=True
        )
    
    with tab2:
        # Success rate bar chart
        fig = px.bar(
            df,
            x="Academic Standard",
            y="Success Rate Value",
            title="Standards Success Rate Comparison",
            labels={"Success Rate Value": "Success Rate (%)"},
            color="Success Rate Value",
            color_continuous_scale="RdYlGn",
            range_color=[0, 100]
        )
        fig.update_layout(
            xaxis_title="Academic Standard",
            yaxis_title="Success Rate (%)",
            showlegend=False,
            height=500
        )
        st.plotly_chart(fig, use_container_width=True)
        
        # Stacked bar chart for credit distribution
        fig2 = go.Figure(data=[
            go.Bar(name='Full Credit', x=df['Academic Standard'], y=df['Full Credit (✓)'], marker_color='green'),
            go.Bar(name='Partial Credit', x=df['Academic Standard'], y=df['Partial Credit (O)'], marker_color='yellow'),
            go.Bar(name='No Credit', x=df['Academic Standard'], y=df['No Credit (X)'], marker_color='red')
        ])
        fig2.update_layout(
            barmode='stack',
            title='Credit Distribution by Standard',
            xaxis_title='Academic Standard',
            yaxis_title='Number of Students',
            height=500
        )
        st.plotly_chart(fig2, use_container_width=True)
    
    with tab3:
        # Identify strengths and weaknesses
        strongest = df.nlargest(3, 'Success Rate Value')
        weakest = df.nsmallest(3, 'Success Rate Value')
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("#### 💪 Strongest Standards")
            for _, row in strongest.iterrows():
                st.success(f"**{row['Academic Standard']}**: {row['Success Rate']}")
        
        with col2:
            st.markdown("#### 🎯 Standards Needing Focus")
            for _, row in weakest.iterrows():
                st.error(f"**{row['Academic Standard']}**: {row['Success Rate']}")
    
    st.markdown("---")
    
    # Student Filters
    st.subheader("🔍 Student Filters")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        if parser.lexile_values:
            lexile_min, lexile_max = st.slider(
                "Lexile Range",
                min_value=int(min(parser.lexile_values)),
                max_value=int(max(parser.lexile_values)),
                value=(int(min(parser.lexile_values)), int(max(parser.lexile_values)))
            )
        else:
            lexile_min, lexile_max = 0, 2000
    
    with col2:
        proficiency_filter = st.multiselect(
            "Proficiency Level",
            options=sorted(set(parser.proficiency_levels)),
            default=sorted(set(parser.proficiency_levels))
        )
    
    with col3:
        search_student = st.text_input("Search Student Name", placeholder="Enter name...")
    
    # Filter students
    filtered_students = []
    for name in set(parser.student_names):
        # Lexile filter
        student_lexile = parser.student_lexile_map.get(name, 0)
        if not (lexile_min <= student_lexile <= lexile_max):
            continue
        
        # Proficiency filter
        student_prof = parser.student_proficiency_map.get(name, "")
        if student_prof not in proficiency_filter:
            continue
        
        # Name search filter
        if search_student and search_student.lower() not in name.lower():
            continue
        
        filtered_students.append(name)
    
    st.info(f"Showing {len(filtered_students)} of {total_students} students")
    
    # Individual Student Performance
    st.subheader("👩‍🎓 Individual Student Performance")
    
    for name in sorted(filtered_students):
        with st.expander(f"📋 {name} - Lexile: {parser.student_lexile_map.get(name, 'N/A')}L | Level: {parser.student_proficiency_map.get(name, 'N/A')}"):
            student_rows = []
            
            for standard, counts in parser.student_data[name].items():
                total_tests = sum(counts.values())
                success_rate = (counts["Full Credit"] / total_tests * 100) if total_tests > 0 else 0
                
                student_rows.append({
                    "Academic Standard": standard,
                    "Total Tests": total_tests,
                    "Full Credit (✓)": counts["Full Credit"],
                    "Partial Credit (O)": counts["Partial Credit"],
                    "No Credit (X)": counts["No Credit"],
                    "Success Rate": f"{success_rate:.1f}%"
                })
            
            if student_rows:
                student_df = pd.DataFrame(student_rows)
                student_df = student_df.sort_values("Success Rate", ascending=False)
                st.dataframe(student_df, use_container_width=True, hide_index=True)
                
                # Mini chart for student
                fig = px.bar(
                    student_df,
                    x="Academic Standard",
                    y=student_df["Success Rate"].str.replace("%", "").astype(float),
                    title=f"Performance by Standard - {name}",
                    color=student_df["Success Rate"].str.replace("%", "").astype(float),
                    color_continuous_scale="RdYlGn"
                )
                fig.update_layout(height=300, showlegend=False)
                st.plotly_chart(fig, use_container_width=True)
    
    st.markdown("---")
    
    # Export Options
    st.subheader("💾 Export Options")
    col1, col2 = st.columns(2)
    
    with col1:
        # CSV Export
        csv = df.drop('Success Rate Value', axis=1).to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📄 Download Class Overview (CSV)",
            data=csv,
            file_name=f"ilearn_class_overview_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            use_container_width=True
        )
    
    with col2:
        # PDF Export
        report_gen = ReportGenerator(school_name, logo_file)
        pdf_bytes = report_gen.create_pdf(df.drop('Success Rate Value', axis=1), metrics)
        st.download_button(
            label="📑 Download Full Report (PDF)",
            data=pdf_bytes,
            file_name=f"ilearn_report_{datetime.now().strftime('%Y%m%d')}.pdf",
            mime="application/pdf",
            use_container_width=True
        )

# ===============================================================================
# RUN APPLICATION
# ===============================================================================
if __name__ == "__main__":
    main()
