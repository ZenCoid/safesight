from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List
from uuid import UUID
from models.rule import Rule
from schemas.rule_schema import RuleDefinition
from core.database import AsyncSessionLocal

router = APIRouter()

async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

@router.post("/", response_model=RuleDefinition, status_code=201)
async def create_rule(rule_def: RuleDefinition, db: AsyncSession = Depends(get_db)):
    db_rule = Rule(
        id=rule_def.rule_id,
        name=rule_def.rule_name,
        version=rule_def.version,
        enabled=rule_def.enabled,
        definition=rule_def.model_dump(mode='json')  # <-- converts UUIDs to strings
    )
    db.add(db_rule)
    await db.commit()
    await db.refresh(db_rule)
    return RuleDefinition(**db_rule.definition)

@router.get("/", response_model=List[RuleDefinition])
async def list_rules(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Rule))
    rules = result.scalars().all()
    return [RuleDefinition(**r.definition) for r in rules]

@router.get("/{rule_id}", response_model=RuleDefinition)
async def get_rule(rule_id: UUID, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Rule).where(Rule.id == rule_id))
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return RuleDefinition(**rule.definition)

@router.put("/{rule_id}", response_model=RuleDefinition)
async def update_rule(rule_id: UUID, rule_def: RuleDefinition, db: AsyncSession = Depends(get_db)):
    rule = await db.get(Rule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule.name = rule_def.rule_name
    rule.version = rule_def.version
    rule.enabled = rule_def.enabled
    rule.definition = rule_def.model_dump(mode='json')
    await db.commit()
    await db.refresh(rule)
    return RuleDefinition(**rule.definition)

@router.delete("/{rule_id}", status_code=204)
async def delete_rule(rule_id: UUID, db: AsyncSession = Depends(get_db)):
    rule = await db.get(Rule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    await db.delete(rule)
    await db.commit()