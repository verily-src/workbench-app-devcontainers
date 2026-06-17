#!/bin/bash
set -e

echo "Installing common data science packages..."

# Package presets
PYTHON_BASIC="pandas numpy matplotlib seaborn scikit-learn jupyter ipywidgets google-cloud-bigquery google-cloud-storage db-dtypes"
PYTHON_ML="$PYTHON_BASIC tensorflow torch transformers xgboost lightgbm optuna mlflow"
PYTHON_BIO="$PYTHON_BASIC biopython scanpy anndata pysam"
PYTHON_FULL="$PYTHON_ML $PYTHON_BIO plotly dash streamlit"

R_BASIC="tidyverse,ggplot2,dplyr,tidyr,readr,plotly,shiny,DT,bigrquery,googleCloudStorageR"
R_ML="$R_BASIC,caret,randomForest,xgboost,keras,reticulate"
R_BIO="$R_BASIC,Seurat,BiocManager,DESeq2"
R_FULL="$R_ML,data.table,arrow,sparklyr,shinydashboard"

# Install Python packages
if [ "${PYTHONPACKAGES}" != "none" ] && command -v pip &> /dev/null; then
    echo "Installing Python packages (preset: ${PYTHONPACKAGES})..."

    case "${PYTHONPACKAGES}" in
        basic)
            PYTHON_PKGS=$PYTHON_BASIC
            ;;
        ml)
            PYTHON_PKGS=$PYTHON_ML
            ;;
        bio)
            PYTHON_PKGS=$PYTHON_BIO
            ;;
        full)
            PYTHON_PKGS=$PYTHON_FULL
            ;;
    esac

    if [ -n "$PYTHON_PKGS" ]; then
        pip install --no-cache-dir $PYTHON_PKGS
    fi

    # Install custom packages
    if [ -n "${CUSTOMPYTHONPACKAGES}" ]; then
        echo "Installing custom Python packages: ${CUSTOMPYTHONPACKAGES}"
        pip install --no-cache-dir ${CUSTOMPYTHONPACKAGES}
    fi
fi

# Install R packages
if [ "${RPACKAGES}" != "none" ] && command -v R &> /dev/null; then
    echo "Installing R packages (preset: ${RPACKAGES})..."

    case "${RPACKAGES}" in
        basic)
            R_PKGS=$R_BASIC
            ;;
        ml)
            R_PKGS=$R_ML
            ;;
        bio)
            R_PKGS=$R_BIO
            ;;
        full)
            R_PKGS=$R_FULL
            ;;
    esac

    if [ -n "$R_PKGS" ]; then
        R --quiet -e "install.packages(strsplit('$R_PKGS', ',')[[1]], repos='https://cran.rstudio.com/', quiet=TRUE)"
    fi

    # Install custom packages
    if [ -n "${CUSTOMRPACKAGES}" ]; then
        echo "Installing custom R packages: ${CUSTOMRPACKAGES}"
        R --quiet -e "install.packages(strsplit('${CUSTOMRPACKAGES}', ',')[[1]], repos='https://cran.rstudio.com/', quiet=TRUE)"
    fi
fi

echo "Package installation complete!"
