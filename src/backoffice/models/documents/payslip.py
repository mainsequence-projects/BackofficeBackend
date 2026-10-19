"""Payslip canonical document contract."""

from datetime import date
from typing import Literal, Self

from pydantic import Field, model_validator

from ..common import DatePeriod, DocumentModel, Employer, Money, NonEmptyStr


class Payslip(DocumentModel):
    """Structured facts from a payslip."""

    document_type: Literal["payslip"] = Field(
        default="payslip", title="Document type", description="Identifies this payload as payslip."
    )
    employee_name: NonEmptyStr = Field(
        title="Employee name", description="Employee name exactly as printed on the payslip."
    )
    employer: Employer = Field(
        title="Employer", description="Employer identity stated by the payslip."
    )
    pay_period: DatePeriod = Field(
        title="Pay period",
        description="Inclusive employment/pay period represented by the payslip.",
    )
    payment_date: date | None = Field(
        default=None, title="Payment date", description="Date on which payment is stated to occur."
    )
    gross_pay: Money = Field(
        title="Gross pay", description="Total pay before deductions, in the stated currency."
    )
    net_pay: Money = Field(
        title="Net pay", description="Amount payable to the employee after deductions."
    )
    deductions: Money | None = Field(
        default=None,
        title="Deductions",
        description="Total deductions stated on the payslip; absence is not a zero deduction.",
    )
    employee_identifier: NonEmptyStr | None = Field(
        default=None,
        title="Employee identifier",
        description="Employer-assigned payroll identifier as printed.",
    )

    @model_validator(mode="after")
    def pay_currencies(self) -> Self:
        if self.gross_pay.currency != self.net_pay.currency:
            raise ValueError("gross_pay and net_pay must use the same currency")
        if self.deductions is not None and self.deductions.currency != self.gross_pay.currency:
            raise ValueError("deductions must use the pay currency")
        return self
