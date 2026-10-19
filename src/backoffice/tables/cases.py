"""Business case types and the exact requirement-policy versions they permit."""

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, info


class CaseTypeRecord(Base):
    __tablename__ = "backoffice__case_type"
    __metatable_identifier__ = "backoffice.case_type"
    __metatable_description__ = "One business case type, such as account opening, new loan or document review. Authored by Back Office to name the business purpose while all types share the same evidence and evaluation engine."
    __metatable_labels__ = ("casework", "reference-data", "requirements")

    key: Mapped[str] = mapped_column(
        String(80),
        primary_key=True,
        info=info(
            "Case type key", "Stable business process key, such as account_opening or new_loan."
        ),
    )
    name: Mapped[str] = mapped_column(
        String(160), info=info("Case type name", "Human-readable name of the business process.")
    )
    description: Mapped[str] = mapped_column(
        String(500),
        info=info(
            "Description", "Business purpose of this case type; does not define evidence rules."
        ),
    )


class CaseTypeDocumentSetRecord(Base):
    __tablename__ = "backoffice__case_type_document_set"
    __metatable_identifier__ = "backoffice.case_type_document_set"
    __metatable_description__ = "One permitted document-set version for one business case type. Back Office maintains this explicit association so case creation cannot select a policy intended for another business process."
    __metatable_labels__ = ("casework", "requirements", "policy")
    __table_args__ = (
        ForeignKeyConstraint(
            ["set_key", "set_version"],
            [
                "backoffice__document_set_version.set_key",
                "backoffice__document_set_version.version",
            ],
        ),
    )

    case_type_key: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("backoffice__case_type.key"),
        primary_key=True,
        info=info(
            "Case type key", "Business process permitted to use this published requirement policy."
        ),
    )
    set_key: Mapped[str] = mapped_column(
        String(120),
        primary_key=True,
        info=info("Document set key", "Stable key of the permitted requirement definition."),
    )
    set_version: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        info=info(
            "Document set version",
            "Exact permitted policy version; a new version needs an explicit association.",
        ),
    )
