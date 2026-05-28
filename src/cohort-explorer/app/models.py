from sqlalchemy import Float, Index, Integer, Numeric, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Sample(Base):
    __tablename__ = "samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # Identifiers
    subject_id: Mapped[str] = mapped_column(Text, index=True)
    gtex_sample_id: Mapped[str] = mapped_column(Text, unique=True)
    specimen_id: Mapped[str | None] = mapped_column(Text)
    dbgap_sample_id: Mapped[str | None] = mapped_column(Text)
    submitter_id: Mapped[str | None] = mapped_column(Text)
    srr_id: Mapped[str | None] = mapped_column(Text)

    # Filterable dimensions
    tissue_type: Mapped[str] = mapped_column(Text, index=True)
    tissue_type_detail: Mapped[str] = mapped_column(Text, index=True)
    autolysis_score: Mapped[str | None] = mapped_column(Text, index=True)
    current_material_type: Mapped[str | None] = mapped_column(Text, index=True)
    sample_collection_kit: Mapped[str | None] = mapped_column(Text, index=True)
    rin_number: Mapped[float | None] = mapped_column(Numeric(3, 1))
    total_ischemic_time: Mapped[float | None] = mapped_column(Float)
    paxgene_time: Mapped[float | None] = mapped_column(Float)

    # Scientific context (display-only)
    tissue_location: Mapped[str | None] = mapped_column(Text)
    bss_collection_site: Mapped[str | None] = mapped_column(Text)
    original_material_type: Mapped[str | None] = mapped_column(Text)
    pathology_notes: Mapped[str | None] = mapped_column(Text)
    prosector_comments: Mapped[str | None] = mapped_column(Text)

    # Export targets
    fastq1_path: Mapped[str | None] = mapped_column(Text)
    fastq2_path: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_samples_tissue_pair", "tissue_type", "tissue_type_detail"),
    )
