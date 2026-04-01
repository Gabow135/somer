"""Agente analista de datos especializado.

Ejecuta análisis de datos, genera visualizaciones y produce
reportes estadísticos combinando code_interpreter + sql_query.

Flujo: data_source → load → analyze → visualize → report

Python 3.9+ — ``from __future__ import annotations``.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Tipos ────────────────────────────────────────────────────


class AnalysisType(str, Enum):
    """Tipos de análisis disponibles."""
    DESCRIPTIVE = "descriptive"      # Estadísticas descriptivas
    CORRELATION = "correlation"      # Correlaciones entre variables
    TREND = "trend"                  # Análisis de tendencias temporales
    DISTRIBUTION = "distribution"    # Distribuciones de variables
    COMPARISON = "comparison"        # Comparación entre grupos
    ANOMALY = "anomaly"              # Detección de anomalías
    SUMMARY = "summary"             # Resumen ejecutivo completo
    CUSTOM = "custom"               # Análisis personalizado


@dataclass
class DataSource:
    """Fuente de datos para análisis."""
    source_type: str = "file"   # file, sql, inline
    path: str = ""              # Ruta al archivo o DSN de BD
    query: str = ""             # Query SQL o descripción
    data: Optional[Any] = None  # Datos inline (dict/list)
    format: str = "csv"         # csv, json, excel, sqlite


@dataclass
class AnalysisStep:
    """Paso individual de un análisis."""
    name: str = ""
    code: str = ""
    description: str = ""
    output: str = ""
    files: List[str] = field(default_factory=list)
    duration_secs: float = 0.0
    status: str = "pending"  # pending, running, success, error


@dataclass
class AnalysisResult:
    """Resultado completo de un análisis de datos."""
    title: str = ""
    data_source: str = ""
    analysis_type: AnalysisType = AnalysisType.SUMMARY
    steps: List[AnalysisStep] = field(default_factory=list)
    summary: str = ""
    insights: List[str] = field(default_factory=list)
    visualizations: List[str] = field(default_factory=list)
    statistics: Dict[str, Any] = field(default_factory=dict)
    duration_secs: float = 0.0

    def to_markdown(self) -> str:
        """Convierte el resultado a Markdown."""
        lines = [
            f"# Análisis: {self.title}",
            f"*Fuente: {self.data_source} | Tipo: {self.analysis_type.value}*",
            "",
            "## Resumen",
            self.summary,
            "",
        ]

        if self.insights:
            lines.append("## Insights")
            for i, insight in enumerate(self.insights, 1):
                lines.append(f"{i}. {insight}")
            lines.append("")

        if self.statistics:
            lines.append("## Estadísticas")
            lines.append("```json")
            lines.append(json.dumps(self.statistics, indent=2, default=str))
            lines.append("```")
            lines.append("")

        if self.visualizations:
            lines.append("## Visualizaciones")
            for viz in self.visualizations:
                lines.append(f"- {viz}")
            lines.append("")

        lines.append(f"*Análisis completado en {self.duration_secs:.1f}s*")
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "data_source": self.data_source,
            "analysis_type": self.analysis_type.value,
            "summary": self.summary,
            "insights": self.insights,
            "statistics": self.statistics,
            "visualizations": self.visualizations,
            "steps": [
                {"name": s.name, "status": s.status, "duration": s.duration_secs}
                for s in self.steps
            ],
            "duration_secs": self.duration_secs,
        }


# ── Code Templates ───────────────────────────────────────────


_LOAD_CSV_TEMPLATE = """
import pandas as pd
df = pd.read_csv("{path}")
print(f"Shape: {{df.shape}}")
print(f"Columns: {{list(df.columns)}}")
print(f"\\nDtypes:\\n{{df.dtypes}}")
print(f"\\nPrimeras filas:\\n{{df.head()}}")
print(f"\\nNulos:\\n{{df.isnull().sum()}}")
"""

_DESCRIPTIVE_TEMPLATE = """
import pandas as pd
df = pd.read_csv("{path}")
print("## Estadísticas Descriptivas\\n")
print(df.describe(include='all').to_string())
print(f"\\n## Correlaciones Numéricas\\n")
numeric_df = df.select_dtypes(include='number')
if len(numeric_df.columns) > 1:
    print(numeric_df.corr().to_string())
"""

_DISTRIBUTION_TEMPLATE = """
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

df = pd.read_csv("{path}")
numeric_cols = df.select_dtypes(include='number').columns[:6]

fig, axes = plt.subplots(len(numeric_cols), 2, figsize=(14, 4*len(numeric_cols)))
if len(numeric_cols) == 1:
    axes = [axes]

for i, col in enumerate(numeric_cols):
    axes[i][0].hist(df[col].dropna(), bins=30, edgecolor='black', alpha=0.7)
    axes[i][0].set_title(f'Distribución: {{col}}')
    axes[i][0].set_xlabel(col)

    sns.boxplot(data=df, y=col, ax=axes[i][1])
    axes[i][1].set_title(f'Box Plot: {{col}}')

plt.tight_layout()
save_figure(fig, "distributions")
print("Distribuciones generadas.")
"""

_CORRELATION_TEMPLATE = """
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

df = pd.read_csv("{path}")
numeric_df = df.select_dtypes(include='number')

fig, ax = plt.subplots(figsize=(10, 8))
sns.heatmap(numeric_df.corr(), annot=True, cmap='coolwarm', center=0,
            fmt='.2f', ax=ax, square=True)
ax.set_title('Matriz de Correlaciones')
plt.tight_layout()
save_figure(fig, "correlations")

# Top correlaciones
corr = numeric_df.corr()
pairs = []
for i in range(len(corr.columns)):
    for j in range(i+1, len(corr.columns)):
        pairs.append((corr.columns[i], corr.columns[j], corr.iloc[i,j]))
pairs.sort(key=lambda x: abs(x[2]), reverse=True)
print("## Top Correlaciones")
for a, b, r in pairs[:10]:
    print(f"  {{a}} ↔ {{b}}: {{r:.3f}}")
"""

_TREND_TEMPLATE = """
import pandas as pd
import matplotlib.pyplot as plt

df = pd.read_csv("{path}")
# Buscar columna temporal
date_cols = [c for c in df.columns if any(k in c.lower() for k in ['date','time','fecha','timestamp'])]
if date_cols:
    df[date_cols[0]] = pd.to_datetime(df[date_cols[0]], errors='coerce')
    df = df.sort_values(date_cols[0])
    numeric_cols = df.select_dtypes(include='number').columns[:4]

    fig, axes = plt.subplots(len(numeric_cols), 1, figsize=(14, 4*len(numeric_cols)), sharex=True)
    if len(numeric_cols) == 1:
        axes = [axes]

    for i, col in enumerate(numeric_cols):
        axes[i].plot(df[date_cols[0]], df[col], alpha=0.7)
        axes[i].set_title(f'Tendencia: {{col}}')
        axes[i].set_ylabel(col)

    plt.xlabel(date_cols[0])
    plt.tight_layout()
    save_figure(fig, "trends")
    print("Tendencias generadas.")
else:
    print("No se encontró columna temporal para análisis de tendencias.")
"""

_ANOMALY_TEMPLATE = """
import pandas as pd
import numpy as np

df = pd.read_csv("{path}")
numeric_cols = df.select_dtypes(include='number').columns

print("## Detección de Anomalías (IQR)\\n")
anomaly_count = 0
for col in numeric_cols:
    Q1 = df[col].quantile(0.25)
    Q3 = df[col].quantile(0.75)
    IQR = Q3 - Q1
    lower = Q1 - 1.5 * IQR
    upper = Q3 + 1.5 * IQR
    outliers = df[(df[col] < lower) | (df[col] > upper)]
    if len(outliers) > 0:
        pct = len(outliers) / len(df) * 100
        print(f"  {{col}}: {{len(outliers)}} anomalías ({{pct:.1f}}%) — rango normal: [{{lower:.2f}}, {{upper:.2f}}]")
        anomaly_count += len(outliers)

if anomaly_count == 0:
    print("  No se detectaron anomalías significativas.")
else:
    print(f"\\nTotal anomalías detectadas: {{anomaly_count}}")
"""


# ── DataAnalystAgent ─────────────────────────────────────────


class DataAnalystAgent:
    """Agente de análisis de datos.

    Uso:
        agent = DataAnalystAgent(code_exec_func=my_code_interpreter)
        result = await agent.analyze(
            source=DataSource(path="datos.csv"),
            analysis_type=AnalysisType.SUMMARY,
        )
    """

    # Mapping de tipo → template
    _TEMPLATES: Dict[AnalysisType, str] = {
        AnalysisType.DESCRIPTIVE: _DESCRIPTIVE_TEMPLATE,
        AnalysisType.DISTRIBUTION: _DISTRIBUTION_TEMPLATE,
        AnalysisType.CORRELATION: _CORRELATION_TEMPLATE,
        AnalysisType.TREND: _TREND_TEMPLATE,
        AnalysisType.ANOMALY: _ANOMALY_TEMPLATE,
    }

    def __init__(
        self,
        *,
        code_exec_func: Optional[Callable[[str, str], Awaitable[Dict[str, Any]]]] = None,
        sql_exec_func: Optional[Callable[[str, str], Awaitable[str]]] = None,
        llm_func: Optional[Callable[[str], Awaitable[str]]] = None,
    ) -> None:
        """
        Args:
            code_exec_func: async (code, description) -> {output, files, ...}
            sql_exec_func: async (query, connection) -> results_string
            llm_func: async (prompt) -> response_string
        """
        self._code_exec = code_exec_func
        self._sql_exec = sql_exec_func
        self._llm = llm_func

    async def analyze(
        self,
        source: DataSource,
        *,
        analysis_type: AnalysisType = AnalysisType.SUMMARY,
        custom_code: str = "",
        title: str = "",
    ) -> AnalysisResult:
        """Ejecuta un análisis completo sobre los datos."""
        start = time.time()
        result = AnalysisResult(
            title=title or f"Análisis de {source.path or 'datos'}",
            data_source=source.path or source.query,
            analysis_type=analysis_type,
        )

        if not self._code_exec:
            result.summary = "Error: code_exec_func no configurado."
            return result

        # 1. Si es SQL, extraer datos primero
        if source.source_type == "sql" and self._sql_exec:
            step = AnalysisStep(name="extract_data", description="Extrayendo datos de SQL")
            try:
                sql_result = await self._sql_exec(source.query, source.path)
                step.output = sql_result
                step.status = "success"
            except Exception as exc:
                step.output = str(exc)
                step.status = "error"
            result.steps.append(step)

        # 2. Ejecutar análisis según tipo
        if analysis_type == AnalysisType.SUMMARY:
            # Ejecutar múltiples análisis
            for atype in [AnalysisType.DESCRIPTIVE, AnalysisType.DISTRIBUTION, AnalysisType.ANOMALY]:
                step = await self._run_analysis_step(source, atype)
                result.steps.append(step)
                if step.files:
                    result.visualizations.extend(step.files)
        elif analysis_type == AnalysisType.CUSTOM:
            step = await self._run_custom_step(custom_code, "Análisis personalizado")
            result.steps.append(step)
            if step.files:
                result.visualizations.extend(step.files)
        else:
            step = await self._run_analysis_step(source, analysis_type)
            result.steps.append(step)
            if step.files:
                result.visualizations.extend(step.files)

        # 3. Compilar resultados
        all_outputs = "\n\n".join(
            s.output for s in result.steps if s.output and s.status == "success"
        )

        if self._llm and all_outputs:
            synthesis = await self._synthesize_results(
                result.title, all_outputs, analysis_type,
            )
            result.summary = synthesis.get("summary", all_outputs[:1000])
            result.insights = synthesis.get("insights", [])
            result.statistics = synthesis.get("statistics", {})
        else:
            result.summary = all_outputs[:2000] if all_outputs else "Sin resultados."

        result.duration_secs = round(time.time() - start, 2)
        return result

    async def _run_analysis_step(
        self,
        source: DataSource,
        analysis_type: AnalysisType,
    ) -> AnalysisStep:
        """Ejecuta un paso de análisis individual."""
        template = self._TEMPLATES.get(analysis_type, "")
        if not template:
            return AnalysisStep(
                name=analysis_type.value,
                status="error",
                output=f"Template no disponible para: {analysis_type.value}",
            )

        code = template.format(path=source.path)
        return await self._run_custom_step(code, analysis_type.value)

    async def _run_custom_step(self, code: str, description: str) -> AnalysisStep:
        """Ejecuta código personalizado."""
        step = AnalysisStep(name=description, code=code, description=description)
        start = time.time()

        try:
            exec_result = await self._code_exec(code, description)
            step.output = exec_result.get("output", "")
            step.files = exec_result.get("files", [])
            step.status = "success" if exec_result.get("exit_code", 1) == 0 else "error"
            if step.status == "error":
                step.output += f"\nError: {exec_result.get('error_output', '')}"
        except Exception as exc:
            step.status = "error"
            step.output = str(exc)

        step.duration_secs = round(time.time() - start, 2)
        return step

    async def _synthesize_results(
        self,
        title: str,
        outputs: str,
        analysis_type: AnalysisType,
    ) -> Dict[str, Any]:
        """Sintetiza resultados del análisis usando LLM."""
        if not self._llm:
            return {}

        prompt = (
            f"Análisis de datos: {title}\n"
            f"Tipo: {analysis_type.value}\n\n"
            f"Resultados del análisis:\n{outputs[:4000]}\n\n"
            "Genera un JSON con:\n"
            '- "summary": resumen ejecutivo de los hallazgos (2-3 párrafos)\n'
            '- "insights": lista de 3-5 insights accionables\n'
            '- "statistics": dict con las métricas clave encontradas\n'
            "\nResponde SOLO el JSON."
        )

        try:
            response = await self._llm(prompt)
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
        except Exception as exc:
            logger.warning("Error sintetizando análisis: %s", exc)

        return {}
