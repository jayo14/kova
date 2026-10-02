import pytest
from app.modules.exploration.service import extract_project_name


def test_extract_project_name_strips_www():
    assert extract_project_name("www.summastudy.com.ng") == "SummaStudy"
    assert extract_project_name("https://www.summastudy.com.ng") == "SummaStudy"
    assert extract_project_name("www2.example.com") == "Example"


def test_extract_project_name_handles_subdomains():
    assert extract_project_name("app.my-app.com") == "My App"
    assert extract_project_name("dev.portal.example.org") == "Example"


def test_extract_project_name_handles_kebab_and_snake():
    assert extract_project_name("https://my-quiz-app.vercel.app") == "My Quiz App"
    assert extract_project_name("cool_service.co.uk") == "Cool Service"


def test_extract_project_name_handles_localhost():
    assert extract_project_name("localhost:3000") == "Localhost"
    assert extract_project_name("127.0.0.1:8000") == "Localhost"
