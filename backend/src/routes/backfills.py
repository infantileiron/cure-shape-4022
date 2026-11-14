from fastapi import APIRouter,Depends
from src.config.database import db_session
from src.controllers.auth import current_user,writer
from src.schemas.backfill import BackfillBatchInput,SegmentInput
from src.services import backfills as service
router=APIRouter(prefix='/backfills')
@router.get('')
def listing(db=Depends(db_session),user=Depends(current_user)):return service.listing(db)
@router.post('')
def create(payload:BackfillBatchInput,db=Depends(db_session),user=Depends(writer)):return service.create(db,payload)
@router.get('/{batch_id}')
def detail(batch_id:str,db=Depends(db_session),user=Depends(current_user)):return service.detail(db,batch_id)
@router.post('/{batch_id}/segments')
def receive(batch_id:str,payload:SegmentInput,db=Depends(db_session),user=Depends(writer)):
 return service.receive_segment(db,batch_id,payload)
@router.post('/{batch_id}/publish')
def publish(batch_id:str,db=Depends(db_session),user=Depends(writer)):return service.publish(db,batch_id)
