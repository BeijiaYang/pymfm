import logging
from typing import List
from fastapi import APIRouter, BackgroundTasks
from pymfm.control.algorithms.controller import do_balancing
from pymfm.control.utils import data_input
from service.crud_redis import RedisStorage
from service.data_aux import JobComplete

log = logging.getLogger("server")

balancing_router = APIRouter(
    tags=["balancing"],
)

# XXX handle this via settings in the future
# storage = FileStorage(filepath=Path(__file__).parent / "store")  # MemoryStorage() # RedisStorage()
storage = RedisStorage()


@balancing_router.post("/", response_model_exclude_none=True)
async def create_balancing_task(input: data_input.InputData, background_tasks: BackgroundTasks) -> JobComplete:
    log.info(f"received input data with id=<{input.id}>. Starting algorithm...")
    job = JobComplete(id=input.id, input=input)
    await storage.store(job)
    background_tasks.add_task(do_balancing, job=job, storage=storage)
    return job


@balancing_router.get("/", description="get the ids of all jobs")
async def get_ids_endpoint() -> List[str]:
    return await storage.all_ids()


@balancing_router.get("/{id}")
async def get_result_endpoint(id: str) -> JobComplete:
    output = await storage.read(id)
    if output is None:
        raise HTTPException(404, f"No job with id {id}")
    return output


# XXX is Updating of a task usefull? Does the job need to be finished? Does a data update replace the data or append it? etc
# @balancing_router.put("/{id}")
# async def put_input_endpoint(input: data_input.InputData):
#     start = timer()
#     result_valid = False
#     result = balancer_control(input)
#     output = data_output.df_to_output(result, input.id)
#     log.info(f"received input data with id=<{input.id}>. Starting algorithm...")
#     return {"success": True}


@balancing_router.delete("/{id}")
async def delete_result_endpoint(id: str) -> JobComplete:
    try:
        result = await storage.delete(id)
    except HTTPException as exc:
        raise exc
    return result
