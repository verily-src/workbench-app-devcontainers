import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
from google.cloud import bigquery
from datetime import datetime

PROJECT_ID = "wb-spotless-eggplant-4340"

@st.cache_data
def load_diagnoses_data():
    """Load diagnosis data from BigQuery"""
    client = bigquery.Client()
    query = f"""
    SELECT *
    FROM `{PROJECT_ID}.analysis.DIAGNOSES`
    """
    return client.query(query).to_dataframe()

@st.cache_data
def load_vitals_data():
    """Load vitals data including BP readings"""
    client = bigquery.Client()
    query = f"""
    SELECT
        USUBJID,
        VISIT,
        VISITNUM,
        study_day,
        vs_sbp1_mmhg,
        vs_dbp1_mmhg,
        vs_sbp2_mmhg,
        vs_dbp2_mmhg,
        vs_pulse_bpm
    FROM `{PROJECT_ID}.crf.VS`
    WHERE vs_sbp1_mmhg IS NOT NULL AND vs_dbp1_mmhg IS NOT NULL
    ORDER BY USUBJID, VISITNUM
    """
    return client.query(query).to_dataframe()

def create_bubble_heatmap(df):
    """View 1: Bubble heatmap of clinical labels by category and frequency"""

    # Extract disease columns (mh_* prefix = medical history)
    disease_cols = [col for col in df.columns if col.startswith('mh_') or col.startswith('der_hx_')]

    # Create category mapping
    categories = {
        'Cardiovascular': ['cvd', 'htn', 'afib', 'cad', 'chf', 'mi', 'cva', 'tia', 'pad', 'vhd'],
        'Metabolic': ['diabetes', 'diab1', 'diab2', 'prediabetes', 'dyslipidemia', 'nafld'],
        'Respiratory': ['copd', 'sleepapnea', 'pulm_vasc'],
        'Renal': ['ckd'],
        'Mental Health': ['major_depression', 'bipolar', 'psychoaffective', 'dementia'],
        'Autoimmune': ['ra', 'sle', 'psoriasis', 'psoriatic_arth'],
        'Other': []
    }

    # Calculate frequencies
    data_rows = []
    for col in disease_cols:
        disease_name = col.replace('mh_', '').replace('der_hx_', '').replace('_', ' ').title()

        # Handle both string and numeric types
        try:
            if df[col].dtype == 'object':  # String type
                # Convert to numeric, treating '1' as 1 and everything else as 0
                count = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int).sum()
            else:  # Numeric type
                count = df[col].fillna(0).astype(int).sum()
        except:
            count = 0

        # Find category
        category = 'Other'
        disease_key = col.replace('mh_', '').replace('der_hx_', '')
        for cat, keywords in categories.items():
            if any(kw in disease_key for kw in keywords):
                category = cat
                break

        if count > 0:
            data_rows.append({
                'Disease': disease_name,
                'Category': category,
                'Participant Count': int(count),
                'Frequency': count / len(df) * 100
            })

    bubble_df = pd.DataFrame(data_rows)

    # Check if we have data
    if len(bubble_df) == 0:
        # Create empty figure with message
        fig = go.Figure()
        fig.add_annotation(
            text="No disease data found in the dataset",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=20)
        )
        fig.update_layout(height=400, title='Clinical Labels: Disease Categories & Prevalence')
        return fig, bubble_df

    # Create bubble chart
    fig = px.scatter(
        bubble_df,
        x='Category',
        y='Disease',
        size='Participant Count',
        color='Frequency',
        hover_data=['Participant Count', 'Frequency'],
        color_continuous_scale='Viridis',
        title='Clinical Labels: Disease Categories & Prevalence',
        size_max=50
    )

    fig.update_layout(
        height=600,
        xaxis_title='Disease Category',
        yaxis_title='Condition',
        showlegend=False
    )

    return fig, bubble_df

def create_disease_leaderboard(df):
    """View 2: Disease leaderboard with total participant months"""

    disease_cols = [col for col in df.columns if col.startswith('mh_') or col.startswith('der_hx_')]

    leaderboard_data = []
    for col in disease_cols:
        disease_name = col.replace('mh_', '').replace('der_hx_', '').replace('_', ' ').title()

        # Filter patients with this disease - handle both string and numeric
        try:
            if df[col].dtype == 'object':  # String type
                disease_patients = df[df[col].astype(str) == '1']
            else:  # Numeric type
                disease_patients = df[df[col] == 1]
        except:
            continue

        if len(disease_patients) > 0:
            # Calculate total participant months (using VISITNUM as proxy for months)
            total_months = disease_patients['VISITNUM'].sum() if 'VISITNUM' in disease_patients.columns else 0
            participant_count = len(disease_patients['USUBJID'].unique())

            leaderboard_data.append({
                'Disease': disease_name,
                'Column': col,
                'Participants': participant_count,
                'Total Participant Months': int(total_months) if total_months else 0,
                'Avg Months per Participant': round(total_months / participant_count, 1) if participant_count > 0 else 0
            })

    leaderboard_df = pd.DataFrame(leaderboard_data).sort_values('Total Participant Months', ascending=False) if leaderboard_data else pd.DataFrame()

    # Check if we have data
    if len(leaderboard_df) == 0:
        fig = go.Figure()
        fig.add_annotation(
            text="No disease data available for leaderboard",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=20)
        )
        fig.update_layout(height=400, title='Disease Leaderboard: Total Participant Months')
        return fig, leaderboard_df

    # Create interactive bar chart
    fig = px.bar(
        leaderboard_df.head(20),
        x='Total Participant Months',
        y='Disease',
        orientation='h',
        title='Disease Leaderboard: Total Participant Months',
        hover_data=['Participants', 'Avg Months per Participant'],
        color='Total Participant Months',
        color_continuous_scale='Blues'
    )

    fig.update_layout(
        height=700,
        yaxis={'categoryorder': 'total ascending'},
        showlegend=False
    )

    return fig, leaderboard_df

def create_hypertension_deep_dive(diagnoses_df, vitals_df, selected_disease='Htn'):
    """View 3: Hypertension deep-dive with BP over time grouped by medication"""

    # Map disease name to column
    disease_col = f"mh_{selected_disease.lower().replace(' ', '_')}"
    if disease_col not in diagnoses_df.columns:
        # Try der_hx_ prefix
        disease_col = f"der_hx_{selected_disease.lower().replace(' ', '_')}"

    # Filter patients with the selected disease
    disease_patients = []
    if disease_col in diagnoses_df.columns:
        try:
            if diagnoses_df[disease_col].dtype == 'object':  # String type
                disease_patients = diagnoses_df[diagnoses_df[disease_col].astype(str) == '1']['USUBJID'].unique()
            else:  # Numeric type
                disease_patients = diagnoses_df[diagnoses_df[disease_col] == 1]['USUBJID'].unique()
        except:
            pass

    if len(disease_patients) == 0:
        st.warning(f"No patients found with {selected_disease}")
        return None

    # Get medication info
    med_cols = {
        'ACEI': 'cm_acei',
        'ARB': 'cm_arb',
        'Beta Blocker': 'cm_bb',
        'CCB': 'cm_ccb',
        'Diuretics': 'cm_diuretics'
    }

    # Filter vitals for disease patients
    htn_vitals = vitals_df[vitals_df['USUBJID'].isin(disease_patients)].copy()

    # Add medication info
    htn_vitals = htn_vitals.merge(
        diagnoses_df[['USUBJID'] + list(med_cols.values())],
        on='USUBJID',
        how='left'
    )

    # Determine primary medication for each patient
    def get_primary_med(row):
        for med_name, col_name in med_cols.items():
            if col_name in row:
                val = str(row[col_name]) if pd.notna(row[col_name]) else '0'
                if val == '1' or val == '1.0':
                    return med_name
        return 'No HTN Medication'

    htn_vitals['Medication Group'] = htn_vitals.apply(get_primary_med, axis=1)

    # Calculate average BP (use reading 1)
    htn_vitals['Avg_SBP'] = htn_vitals['vs_sbp1_mmhg']
    htn_vitals['Avg_DBP'] = htn_vitals['vs_dbp1_mmhg']

    # Group by medication and visit
    grouped = htn_vitals.groupby(['Medication Group', 'VISITNUM']).agg({
        'Avg_SBP': ['mean', 'std'],
        'Avg_DBP': ['mean', 'std'],
        'USUBJID': 'count'
    }).reset_index()

    grouped.columns = ['Medication Group', 'Visit Number', 'SBP_Mean', 'SBP_Std', 'DBP_Mean', 'DBP_Std', 'Patient_Count']

    # Create line chart with error ribbons
    fig = go.Figure()

    med_groups = grouped['Medication Group'].unique()
    colors = px.colors.qualitative.Set2

    for i, med_group in enumerate(med_groups):
        med_data = grouped[grouped['Medication Group'] == med_group].sort_values('Visit Number')

        if len(med_data) > 0:
            color = colors[i % len(colors)]

            # Add SBP line
            fig.add_trace(go.Scatter(
                x=med_data['Visit Number'],
                y=med_data['SBP_Mean'],
                mode='lines+markers',
                name=f'{med_group} - SBP',
                line=dict(color=color, width=2),
                marker=dict(size=8, symbol='circle'),
                showlegend=True
            ))

            # Add SBP std deviation ribbon
            fig.add_trace(go.Scatter(
                x=med_data['Visit Number'].tolist() + med_data['Visit Number'].tolist()[::-1],
                y=(med_data['SBP_Mean'] + med_data['SBP_Std']).tolist() +
                  (med_data['SBP_Mean'] - med_data['SBP_Std']).tolist()[::-1],
                fill='toself',
                fillcolor=color,
                opacity=0.2,
                line=dict(width=0),
                showlegend=False,
                hoverinfo='skip'
            ))

    # Add doctor visit markers (each VISITNUM represents a visit)
    all_visits = htn_vitals[['VISITNUM', 'VISIT']].drop_duplicates().sort_values('VISITNUM')

    fig.update_layout(
        title=f'{selected_disease.title()}: Average Systolic BP by Medication Group',
        xaxis_title='Doctor Visit Number',
        yaxis_title='Systolic Blood Pressure (mmHg)',
        hovermode='x unified',
        height=600,
        legend=dict(
            orientation='v',
            yanchor='top',
            y=1,
            xanchor='left',
            x=1.02
        )
    )

    # Add horizontal reference lines
    fig.add_hline(y=120, line_dash="dash", line_color="green",
                  annotation_text="Normal (<120)", annotation_position="right")
    fig.add_hline(y=140, line_dash="dash", line_color="orange",
                  annotation_text="Stage 1 HTN (≥140)", annotation_position="right")

    return fig, htn_vitals, grouped

# Main app
def main():
    st.set_page_config(page_title="Clinical Data Dashboard", layout="wide")

    st.title("📊 Clinical Data Dashboard")
    st.markdown("**Workspace:** wb-spotless-eggplant-4340 | **Demo:** BHS Raw Data Processing & Clinical Labels")

    # Load data
    with st.spinner("Loading data from BigQuery..."):
        diagnoses_df = load_diagnoses_data()
        vitals_df = load_vitals_data()

    st.success(f"✅ Loaded {len(diagnoses_df)} diagnosis records and {len(vitals_df)} vital sign measurements")

    # View 1: Bubble Heatmap
    st.header("1️⃣ Bubble Heatmap: Clinical Labels by Category")
    st.markdown("*Bubble size = participant count | Color intensity = prevalence frequency*")

    heatmap_fig, heatmap_data = create_bubble_heatmap(diagnoses_df)
    st.plotly_chart(heatmap_fig, use_container_width=True)

    with st.expander("📊 View raw data"):
        st.dataframe(heatmap_data.sort_values('Participant Count', ascending=False))

    st.markdown("---")

    # View 2: Disease Leaderboard
    st.header("2️⃣ Disease Leaderboard: Total Participant Months")
    st.markdown("*Click a disease name to update the deep-dive view below*")

    leaderboard_fig, leaderboard_data = create_disease_leaderboard(diagnoses_df)
    st.plotly_chart(leaderboard_fig, use_container_width=True)

    # Disease selector
    disease_options = leaderboard_data['Disease'].tolist()
    selected_disease = st.selectbox(
        "Select disease for deep-dive analysis:",
        options=disease_options,
        index=disease_options.index('Htn') if 'Htn' in disease_options else 0
    )

    with st.expander("📊 View leaderboard data"):
        st.dataframe(leaderboard_data)

    st.markdown("---")

    # View 3: Hypertension Deep-Dive (or selected disease)
    st.header(f"3️⃣ {selected_disease.title()} Deep-Dive: BP Trends by Medication")
    st.markdown("*Line = average systolic BP | Ribbon = standard deviation | Markers = doctor visits*")

    result = create_hypertension_deep_dive(diagnoses_df, vitals_df, selected_disease)

    if result:
        deepdive_fig, htn_vitals, grouped_data = result
        st.plotly_chart(deepdive_fig, use_container_width=True)

        # Summary stats
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Patients", len(htn_vitals['USUBJID'].unique()))
        with col2:
            st.metric("Total Visits", len(htn_vitals))
        with col3:
            avg_sbp = htn_vitals['Avg_SBP'].mean()
            st.metric("Avg Systolic BP", f"{avg_sbp:.1f} mmHg")

        with st.expander("📊 View medication group data"):
            st.dataframe(grouped_data.sort_values(['Medication Group', 'Visit Number']))

        with st.expander("📊 View raw vitals data"):
            st.dataframe(htn_vitals[['USUBJID', 'VISIT', 'VISITNUM', 'Medication Group',
                                      'Avg_SBP', 'Avg_DBP']].head(100))

if __name__ == "__main__":
    main()
