Практическо контролно: Чакалня за игра

Модели:
  Нов модел `games.WaitingEntry` (заявка в чакалнята):
   `user` — 1to1 към потребителя → в базата има най-много една текуща заявка на потребител;
   `created_at` — кога е записан.
  Използват се съществуващите `Game`  и `Player`.
  Допустим потребител = няма `Player` в игра със status `waiting` или `active`.

Операции:
  `join_waiting_room(user)`
    ако потребителят не е допустим → `ValidationError`
    ако вече има заявка → `AlreadyWaiting`
    иначе създава `WaitingEntry`.
  `leave_waiting_room(user)`
  `form_game()` - транзакция
    заключва заявките 
    ако са < 3 → връща `None`
    `random.sample` избира 3 различни потребители;
    създава `Game(status=waiting)` и 3 `Player` с цветове r g b и score 0;
    изтрива само трите избрани заявки. 
    При грешка транзакцията се отменя

Задействане:
  На всеки `join_waiting_room(user)` се вика `form_game()`
  За тестване директно се вика `form_game()`

HTTP API (изисква login, session auth)
  `POST /api/waiting-room/join/` → `201` (записан; връща `game_id`, ако е сформирана игра),
  `409` ако вече чака, `400` ако участва в waiting/active игра.
  `POST /api/waiting-room/leave/` → `204` ако заявката е премахната, `404` ако не чака.

Тестове
  5 чакащи → 1 нова waiting игра,2 заявки остават в чакалня.
  2 чакащи → `None`