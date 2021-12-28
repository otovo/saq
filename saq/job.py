import dataclasses
import enum
import typing

from saq.utils import now, seconds, uuid1


class Status(str, enum.Enum):
    NEW = "new"
    DEFERRED = "deferred"
    QUEUED = "queued"
    ACTIVE = "active"
    ABORTED = "aborted"
    FAILED = "failed"
    COMPLETE = "complete"


@dataclasses.dataclass
class Job:
    """
    Main job class representing a run of a function.

    User Provided Arguments
        function: the async function name to run
        kwargs: kwargs to pass to the function
        queue: the saq.Queue object associated with the job
        job_id: unique identifier of a job, defaults to uuid1, can be passed in to avoid duplicate jobs
        timeout: the maximum amount of time a job can run for in seconds, defaults to 10 (0 means disabled)
        heartbeat: the maximum amount of time a job can survive without a heartebat in seconds, defaults to 0 (disabled)
        retries: the maximum number of attempts to retry a job, defaults to 1
        ttl: the maximum time in seconds to store information about a job including results, defaults to 60
        scheduled: epoch seconds for when the job should be scheduled, defaults to 0 (schedule right away)
    Framework Set Properties
        attempts: number of attempts a job has had
        completed: job completion time epoch seconds
        enqueued: job enqueued time epoch seconds
        started: job started time epoch seconds
        touched: job touched/updated time epoch seconds
        results: dictionary containing the results, this is the return of the function provided, must be serializable, defaults to json
        error: stack trace if an runtime error occurs
        status: Status Enum, defaulst to Status.New
    """

    function: str
    kwargs: typing.Optional[dict] = None
    queue: typing.Optional["Queue"] = None
    job_id: str = dataclasses.field(default_factory=uuid1)
    timeout: int = 10
    heartbeat: int = 0
    retries: int = 1
    ttl: int = 60
    scheduled: int = 0
    attempts: int = 0
    completed: int = 0
    enqueued: int = 0
    started: int = 0
    touched: int = 0
    result: typing.Optional[dict] = None
    error: typing.Optional[str] = None
    status: Status = Status.NEW

    def __repr__(self):
        kwargs = ", ".join(
            f"{k}={v}"
            for k, v in {
                "function": self.function,
                "kwargs": self.kwargs,
                "queue": self.queue.name,
                "job_id": self.job_id,
                "process_ms": self.duration("process"),
                "start_ms": self.duration("start"),
                "total_ms": self.duration("total"),
                "attempts": self.attempts,
                "result": self.result,
                "error": self.error,
                "status": self.status,
            }.items()
            if v is not None
        )
        return f"Job<{kwargs}>"

    def duration(self, kind):
        """
        Returns the duration of the job given kind.

        Kind can be process (how long it took to process),
        start (how long it took to start), or total.
        """
        if kind == "process":
            return self._duration(self.completed, self.started)
        if kind == "start":
            return self._duration(self.started, self.enqueued)
        if kind == "total":
            return self._duration(self.completed, self.enqueued)
        raise ValueError(f"Unknown duration type: {kind}")

    def _duration(self, a, b):
        return a - b if a and b else None

    @property
    def stuck(self):
        """Checks if an active job is passed it's timeout or heartbeat."""
        current = now()
        return (self.status == Status.ACTIVE) and (
            seconds(current - self.started) > self.timeout
            or (self.heartbeat and seconds(current - self.touched) > self.heartbeat)
        )

    async def enqueue(self, queue=None):
        """
        Enqueues the job to it's queue or a provided one.

        A job that already has a queue cannot be re-enqueued.

        Returns a new instance of the job that was actually queued
        (job_ids are unique and so a different job may already have been queued).
        """
        queue = queue or self.queue
        assert queue, "Queue unspecified"
        return await queue.enqueue(self)

    async def abort(self):
        """Tries to abort the job."""
        await self.queue.abort(self)

    async def finish(self, status, *, result=None, error=None):
        """Finishes the job with a Job.Status, result, and or error."""
        await self.queue.finish(self, status, result=result, error=error)

    async def retry(self, error):
        """Retries the job by removing it from active and requeueing it."""
        await self.queue.retry(self, error)

    async def update(self):
        """Updates the stored job in redis."""
        await self.queue.update(self)
