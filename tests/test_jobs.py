import asyncio
import unittest

from app.jobs import active_job, begin_job, cancel_job, end_job


class TestJobs(unittest.IsolatedAsyncioTestCase):
    async def test_begin_busy_and_end(self):
        data: dict = {}
        task = begin_job(data, 42)
        self.assertIsNotNone(task)
        self.assertIs(active_job(data, 42), task)
        # A second job for the same user is refused while one runs.
        self.assertIsNone(begin_job(data, 42))
        # Another user is unaffected.
        self.assertIsNotNone(begin_job(data, 43))
        end_job(data, 42, task)
        self.assertIsNone(active_job(data, 42))

    async def test_cancel_actually_stops_the_job(self):
        data: dict = {}

        async def worker():
            begin_job(data, 7)
            try:
                await asyncio.sleep(60)
            finally:
                end_job(data, 7, asyncio.current_task())

        task = asyncio.create_task(worker())
        await asyncio.sleep(0.05)
        self.assertTrue(cancel_job(data, 7))
        with self.assertRaises(asyncio.CancelledError):
            await task
        # After cancellation there is nothing left to cancel.
        self.assertFalse(cancel_job(data, 7))
        self.assertIsNone(active_job(data, 7))


if __name__ == "__main__":
    unittest.main()
