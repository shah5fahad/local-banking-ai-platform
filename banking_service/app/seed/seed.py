"""Seed the database with demo roles, users, accounts, beneficiaries, offers, and credit cards."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import BankingSettings
from app.core.security import hash_password, hash_pin, sha256_hash
from app.models.account import BankAccount
from app.models.beneficiary import Beneficiary
from app.models.credit_card import CreditCard, CreditCardStatement
from app.models.loan import LoanOffer
from app.models.user import Role, User


def run_seed(db: Session, settings: BankingSettings) -> None:
    """Populate database with development and demo fixtures."""
    now = datetime.now(timezone.utc)
    print("Starting database seed...")

    # 1. Create Roles
    roles: dict[str, Role] = {}
    for role_name in ["CUSTOMER", "ADMIN", "AUDITOR"]:
        role = db.scalar(select(Role).where(Role.name == role_name))
        if not role:
            role = Role(id=str(uuid.uuid4()), name=role_name)
            db.add(role)
            db.flush()
            print(f"Created role: {role_name}")
        roles[role_name] = role

    # 2. Create Admin user
    admin_email = "admin@bank.local"
    admin_user = db.scalar(select(User).where(User.email == admin_email))
    if not admin_user:
        admin_user = User(
            id=str(uuid.uuid4()),
            email=admin_email,
            phone="+919999900000",
            full_name="System Administrator",
            password_hash=hash_password("Admin@Bank2024!"),
            transaction_pin_hash=hash_pin("9999"),
            is_active=True,
            roles=[roles["ADMIN"], roles["AUDITOR"]],
        )
        db.add(admin_user)
        db.flush()
        print(f"Created Admin user: {admin_email} (password: Admin@Bank2024!)")

    # 3. Create Demo Customer
    cust_email = "customer@bank.local"
    cust_user = db.scalar(select(User).where(User.email == cust_email))
    if not cust_user:
        cust_user = User(
            id=str(uuid.uuid4()),
            email=cust_email,
            phone="+919876543210",
            full_name="Demo Customer",
            password_hash=hash_password("Customer@Bank2024!"),
            transaction_pin_hash=hash_pin("1234"),
            is_active=True,
            roles=[roles["CUSTOMER"]],
        )
        db.add(cust_user)
        db.flush()
        print(f"Created Customer: {cust_email} (password: Customer@Bank2024!, PIN: 1234)")

    # 4. Create Bank Account for Demo Customer
    account_number = "100200300400"
    acc_hash = sha256_hash(account_number)
    account = db.scalar(
        select(BankAccount).where(
            BankAccount.user_id == cust_user.id,
            BankAccount.account_number_hash == acc_hash,
        )
    )
    if not account:
        account = BankAccount(
            id=str(uuid.uuid4()),
            user_id=cust_user.id,
            holder_name=cust_user.full_name,
            account_number_encrypted=f"ENC_{account_number}",
            account_number_last4="0400",
            account_number_hash=acc_hash,
            ifsc="HDFC0001234",
            bank_name="HDFC Bank",
            branch_name="Connaught Place",
            account_type="SAVINGS",
            balance_minor=10_000_000,  # Rs 100,000.00
            currency="INR",
            verification_status="VERIFIED",
            status="ACTIVE",
        )
        db.add(account)
        db.flush()
        print(f"Created Bank Account: XXXXXX0400 with balance Rs 100,000.00")

    # 5. Create Beneficiary for Demo Customer
    bene_acc = "998877665544"
    bene_hash = sha256_hash(bene_acc)
    bene = db.scalar(
        select(Beneficiary).where(
            Beneficiary.user_id == cust_user.id,
            Beneficiary.account_hash == bene_hash,
        )
    )
    if not bene:
        bene = Beneficiary(
            id=str(uuid.uuid4()),
            user_id=cust_user.id,
            name="Rahul Sharma",
            nickname="Rahul",
            account_number_encrypted=f"ENC_{bene_acc}",
            last4="5544",
            account_hash=bene_hash,
            ifsc="SBIN0004321",
            bank_name="State Bank of India",
            verification_status="VERIFIED",
            approval_status="VERIFIED",
            status="ACTIVE",
        )
        db.add(bene)
        db.flush()
        print("Created Beneficiary: Rahul Sharma (SBI XXXXXX5544, pre-verified)")

    # 6. Create Loan Offers
    existing_offer = db.scalar(select(LoanOffer).where(LoanOffer.loan_type == "PERSONAL"))
    if not existing_offer:
        personal_offer = LoanOffer(
            id=str(uuid.uuid4()),
            user_id=cust_user.id,
            loan_type="PERSONAL",
            max_amount_minor=50_000_000,  # Rs 500,000
            rate_bps=1050,                 # 10.50%
            min_tenure_months=12,
            max_tenure_months=60,
            valid_till=now + timedelta(days=180),
            status="ACTIVE",
        )
        home_offer = LoanOffer(
            id=str(uuid.uuid4()),
            user_id=None,  # generic offer
            loan_type="HOME",
            max_amount_minor=500_000_000,  # Rs 5,000,000
            rate_bps=850,                  # 8.50%
            min_tenure_months=60,
            max_tenure_months=240,
            valid_till=now + timedelta(days=365),
            status="ACTIVE",
        )
        db.add(personal_offer)
        db.add(home_offer)
        db.flush()
        print("Created Loan Offers: Personal Loan (10.50%) and Home Loan (8.50%)")

    # 7. Create Credit Card & Statement for Demo Customer
    card = db.scalar(select(CreditCard).where(CreditCard.user_id == cust_user.id))
    if not card:
        card = CreditCard(
            id=str(uuid.uuid4()),
            user_id=cust_user.id,
            card_token="tok_visa_infinite_4321",
            last4="4321",
            network="VISA",
            credit_limit_minor=20_000_000,  # Rs 200,000
            outstanding_minor=1_500_000,     # Rs 15,000
            status="ACTIVE",
        )
        db.add(card)
        db.flush()

        stmt_obj = CreditCardStatement(
            id=str(uuid.uuid4()),
            card_id=card.id,
            period_start=now - timedelta(days=30),
            period_end=now,
            total_due_minor=1_500_000,
            min_due_minor=150_000,
            due_date=now + timedelta(days=15),
            status="UNPAID",
        )
        db.add(stmt_obj)
        db.flush()
        print(f"Created Credit Card: VISA ending 4321 with Rs 15,000 outstanding")

    db.commit()
    print("Database seed completed successfully!")
