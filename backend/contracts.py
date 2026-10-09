"""API contracts. Keep secrets out of validation errors and response schemas."""
from typing import Any, Generic, Literal, TypeVar
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictInt, field_validator, model_validator

T = TypeVar('T')


class Envelope(BaseModel, Generic[T]):
    code: int | str = 0
    message: str = '成功'
    data: T | None = None
    request_id: str


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Name(Input):
    name: str = Field(min_length=1, max_length=100)

    @field_validator('name')
    @classmethod
    def trim(cls, value):
        if not value.strip():
            raise ValueError('不能为空')
        return value.strip()


class BookUpdate(Input):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    author: str | None = Field(default=None, max_length=100)
    category: str | None = Field(default=None, max_length=50)
    description: str | None = Field(default=None, max_length=1000)

    @field_validator('name', 'author', 'category', 'description')
    @classmethod
    def trim_book_text(cls, value):
        if value is None:
            return value
        return value.strip()

    @model_validator(mode='after')
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError('至少提供一个要修改的字段')
        if self.name is not None and not self.name:
            raise ValueError('书名不能为空')
        return self


class SessionInput(Name):
    name: str = '新会话'


class Question(Input):
    question: str = Field(min_length=1, max_length=4000)

    @field_validator('question')
    @classmethod
    def trim(cls, value):
        if not value.strip():
            raise ValueError('不能为空')
        return value.strip()


class Login(Input):
    username: str = Field(min_length=1, max_length=100)
    password: SecretStr = Field(min_length=1, max_length=72)


class Refresh(Input):
    refresh_token: SecretStr = Field(min_length=1, max_length=4096)


class ModelInput(Input):
    mode: Literal['api', 'ollama']
    model: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=1, max_length=2048)
    api_key: SecretStr | None = None


class Preferences(Input):
    last_book_id: str | None = None
    active_session_by_book: dict[str, str] = Field(default_factory=dict, max_length=1000)


class User(BaseModel):
    id: int
    username: str
    nickname: str
    role: str


class Tokens(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int
    user: User | None = None


class ModelSummary(BaseModel):
    mode: str
    model: str
    base_url: str
    has_api_key: bool
    source: str


class FileInfo(BaseModel):
    id: str
    name: str
    size_bytes: int | None = None
    chunk_count: int
    status: str
    uploaded_at: str | None
    book_id: str


class Book(BaseModel):
    id: str
    name: str
    author: str = ''
    category: str = '未分类'
    description: str = ''
    has_cover: bool = False
    created_at: str | None
    file_count: int
    chunk_count: int
    status: str
    visibility: str
    writable: bool
    capabilities: dict[str, bool]


class BookDetail(Book):
    files: list[FileInfo]


class Session(BaseModel):
    id: str
    book_id: str
    name: str
    created_at: str
    updated_at: str


class Source(BaseModel):
    text: str
    metadata: dict[str, Any]
    distance: float | None = None


class ToolCall(BaseModel):
    name: Literal['show_relationship_graph', 'lookup_characters', 'lookup_events']
    arguments: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any]


class Turn(BaseModel):
    turn_id: int
    question: str
    answer: str
    sources: list[Source] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    rejected: bool = False
    soft_reject: bool = False
    min_distance: float | None = None
    created_at: str | None


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class Items(BaseModel, Generic[T]):
    items: list[T]


class Graph(BaseModel):
    format: Literal['mermaid'] = 'mermaid'
    code: str


class Character(BaseModel):
    id: str
    name: str
    identity: str = ''
    description: str = ''
    family: str = ''
    role: str = ''


class Relation(BaseModel):
    source_id: str
    target_id: str
    target_name: str
    relation: str
    type: str | None = None


class Event(BaseModel):
    id: str
    name: str
    chapter: str = ''
    description: str = ''
    characters: list[str] = Field(default_factory=list)


class Exercise(BaseModel):
    id: str
    chapter: str = ''
    difficulty: Literal['easy', 'medium', 'hard']
    question: str
    type: str | None = None
    options: list[str] = Field(default_factory=list)


class ExerciseStart(Input):
    chapters: list[str] = Field(min_length=1, max_length=200)
    difficulty: Literal['easy', 'medium', 'hard'] | None = None


class ExerciseSubmit(Input):
    answers: dict[str, StrictInt] = Field(default_factory=dict)



class Error(Exception):
    def __init__(self, status, code, message, data=None):
        super().__init__(message)
        self.status, self.code, self.message, self.data = status, code, message, data


def missing():
    raise Error(404, 'RESOURCE_NOT_FOUND', '资源不存在或不可访问')


def paginate(items, page, page_size):
    return dict(items=items[(page-1)*page_size:page*page_size], total=len(items), page=page, page_size=page_size)
