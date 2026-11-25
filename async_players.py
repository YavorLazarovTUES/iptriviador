import asyncio
import time

# Прогноза:
#   последователен: ~5 s; ред: start 1, end 1, start 2, end 2 (3 s + 2 s)
#   конкурентен:    ~3 s; ред: start 1, start 2, end 2, end 1 (max(3 s, 2 s))
# Резултат: съвпада с прогнозата (5.0 s и 3.0 s).
#
# Event loop: решава коя задача да работи; при await задачата отстъпва,
# а чакащите продължават, когато събитието им (таймер, отговор) настъпи.
# Конкурентно != паралелно: в една нишка кодът на само една задача
# върви наведнъж; печелим от припокриващото се чакане. Блокиране спира всички.


async def fetch(name, delay):
    print("start", name)
    await asyncio.sleep(delay)
    print("end", name)


async def sequential():
    await fetch(1, 3)
    await fetch(2, 2)


async def concurrent():
    t1 = asyncio.create_task(fetch(1, 3))
    t2 = asyncio.create_task(fetch(2, 2))
    await t1
    await t2


async def main():
    s = time.perf_counter()
    await sequential()
    print("sequential", round(time.perf_counter() - s, 2), "s")

    s = time.perf_counter()
    await concurrent()
    print("concurrent", round(time.perf_counter() - s, 2), "s")


asyncio.run(main())
