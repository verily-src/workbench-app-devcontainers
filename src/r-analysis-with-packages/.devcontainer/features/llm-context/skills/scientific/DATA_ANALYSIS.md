# Data Analysis Skills

**Trigger:** User asks about ML, statistics, visualization, plots, sklearn, regression, or classification.

---

## Quick Reference

| Task | Package | Quick Import |
|------|---------|--------------|
| ML models (classification, regression) | `scikit-learn` | `from sklearn.ensemble import RandomForestClassifier` |
| Statistical tests, regression | `statsmodels` | `import statsmodels.api as sm` |
| Interactive plots | `plotly` | `import plotly.express as px` |
| Statistical visualization | `seaborn` | `import seaborn as sns` |

---

## Scikit-learn (Machine Learning)

**Use for:** Classification, regression, clustering, dimensionality reduction, model evaluation.

### Classification

```python
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import classification_report, confusion_matrix
import pandas as pd

# Load data
df = pd.read_csv('data.csv')
X = df.drop('target', axis=1)
y = df['target']

# Split
X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

# Train
model = RandomForestClassifier(n_estimators=100, random_state=42)
model.fit(X_train, y_train)

# Evaluate
y_pred = model.predict(X_test)
print(classification_report(y_test, y_pred))
print(confusion_matrix(y_test, y_pred))

# Cross-validation
cv_scores = cross_val_score(model, X, y, cv=5)
print(f"CV Accuracy: {cv_scores.mean():.3f} ± {cv_scores.std():.3f}")

# Feature importance
importance = pd.DataFrame({
    'feature': X.columns,
    'importance': model.feature_importances_
}).sort_values('importance', ascending=False)
```

### Regression

```python
from sklearn.linear_model import LinearRegression, Ridge, Lasso
from sklearn.metrics import mean_squared_error, r2_score

model = Ridge(alpha=1.0)
model.fit(X_train, y_train)

y_pred = model.predict(X_test)
print(f"R²: {r2_score(y_test, y_pred):.3f}")
print(f"RMSE: {mean_squared_error(y_test, y_pred, squared=False):.3f}")
```

### Clustering

```python
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

# Scale features
scaler = StandardScaler()
X_scaled = scaler.fit_transform(X)

# K-Means
kmeans = KMeans(n_clusters=3, random_state=42)
clusters = kmeans.fit_predict(X_scaled)

# Evaluate
from sklearn.metrics import silhouette_score
score = silhouette_score(X_scaled, clusters)
print(f"Silhouette Score: {score:.3f}")
```

### Dimensionality Reduction

```python
from sklearn.decomposition import PCA
from sklearn.manifold import TSNE

# PCA
pca = PCA(n_components=2)
X_pca = pca.fit_transform(X_scaled)
print(f"Explained variance: {pca.explained_variance_ratio_.sum():.2%}")

# t-SNE
tsne = TSNE(n_components=2, random_state=42)
X_tsne = tsne.fit_transform(X_scaled)
```

---

## Statsmodels (Statistical Analysis)

**Use for:** Regression with diagnostics, statistical tests, time series.

### Linear Regression with Diagnostics

```python
import statsmodels.api as sm
import pandas as pd

# Add constant for intercept
X_const = sm.add_constant(X)

# Fit OLS
model = sm.OLS(y, X_const).fit()

# Full summary with p-values, R², etc.
print(model.summary())

# Key metrics
print(f"R-squared: {model.rsquared:.3f}")
print(f"Adj. R-squared: {model.rsquared_adj:.3f}")
print(f"F-statistic p-value: {model.f_pvalue:.2e}")

# Coefficients with confidence intervals
print(model.conf_int())
```

### Logistic Regression

```python
model = sm.Logit(y, X_const).fit()
print(model.summary())

# Odds ratios
import numpy as np
odds_ratios = np.exp(model.params)
```

### Statistical Tests

```python
from scipy import stats

# t-test
t_stat, p_value = stats.ttest_ind(group1, group2)

# ANOVA
f_stat, p_value = stats.f_oneway(group1, group2, group3)

# Chi-square test
chi2, p_value, dof, expected = stats.chi2_contingency(contingency_table)

# Correlation
corr, p_value = stats.pearsonr(x, y)
corr, p_value = stats.spearmanr(x, y)

# Normality test
stat, p_value = stats.shapiro(data)
```

---

## Plotly (Interactive Visualization)

**Use for:** Interactive charts, dashboards, web-embeddable plots.

### Basic Plots

```python
import plotly.express as px
import pandas as pd

df = pd.read_csv('data.csv')

# Scatter plot
fig = px.scatter(df, x='x', y='y', color='category', 
                 hover_data=['name'], title='Scatter Plot')
fig.show()

# Bar chart
fig = px.bar(df, x='category', y='value', color='group')
fig.show()

# Line plot
fig = px.line(df, x='date', y='value', color='series')
fig.show()

# Histogram
fig = px.histogram(df, x='value', nbins=30, color='group')
fig.show()

# Box plot
fig = px.box(df, x='category', y='value', color='group')
fig.show()
```

### Advanced Features

```python
import plotly.graph_objects as go

# Multiple traces
fig = go.Figure()
fig.add_trace(go.Scatter(x=x1, y=y1, name='Series 1'))
fig.add_trace(go.Scatter(x=x2, y=y2, name='Series 2'))
fig.update_layout(title='Multi-series Plot')
fig.show()

# Heatmap
fig = px.imshow(correlation_matrix, text_auto=True, color_continuous_scale='RdBu_r')
fig.show()

# 3D scatter
fig = px.scatter_3d(df, x='x', y='y', z='z', color='category')
fig.show()
```

---

## Seaborn (Statistical Visualization)

**Use for:** Publication-quality statistical plots with pandas integration.

### Distribution Plots

```python
import seaborn as sns
import matplotlib.pyplot as plt

# Histogram with KDE
sns.histplot(data=df, x='value', hue='group', kde=True)
plt.show()

# KDE plot
sns.kdeplot(data=df, x='value', hue='group', fill=True)
plt.show()

# Box plot
sns.boxplot(data=df, x='category', y='value', hue='group')
plt.show()

# Violin plot
sns.violinplot(data=df, x='category', y='value', hue='group', split=True)
plt.show()
```

### Relationship Plots

```python
# Scatter with regression line
sns.regplot(data=df, x='x', y='y')
plt.show()

# Joint plot (scatter + marginal distributions)
sns.jointplot(data=df, x='x', y='y', kind='reg')
plt.show()

# Pair plot (all pairwise relationships)
sns.pairplot(df, hue='category')
plt.show()
```

### Heatmaps

```python
# Correlation heatmap
corr = df.corr()
sns.heatmap(corr, annot=True, cmap='coolwarm', center=0)
plt.show()

# Clustermap (hierarchical clustering)
sns.clustermap(corr, annot=True, cmap='coolwarm')
plt.show()
```

### Styling

```python
# Set theme
sns.set_theme(style='whitegrid')  # darkgrid, white, dark, ticks

# Figure size
plt.figure(figsize=(10, 6))

# Save figure
plt.savefig('plot.png', dpi=300, bbox_inches='tight')
```

---

## Installation

```bash
pip install scikit-learn statsmodels plotly seaborn matplotlib pandas
```

---

## See Also

- For domain-specific analysis → `BIOINFORMATICS.md`, `DRUG_DISCOVERY.md`
- For dashboards in Workbench → `DASHBOARD_BUILDER.md`
