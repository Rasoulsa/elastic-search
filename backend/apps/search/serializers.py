from rest_framework import serializers

from .query import (
    DEFAULT_PAGE_SIZE,
    FILTER_FIELDS,
    MAX_PAGE_SIZE,
    MAX_RESULT_WINDOW,
    SearchCriteria,
)

MAX_QUERY_LENGTH = 500
MAX_FILTER_LENGTH = 200
MAX_FILTER_VALUES = 20
SEARCH_WINDOW_MESSAGE = "Requested page exceeds the supported search result window."
SCALAR_QUERY_PARAMETERS = ("q", "page", "page_size")
REPEATED_SCALAR_MESSAGE = "This parameter may only be provided once."


class ProfileSearchParametersSerializer(serializers.Serializer):
    q = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=MAX_QUERY_LENGTH,
        trim_whitespace=True,
    )
    skill = serializers.ListField(
        child=serializers.CharField(
            allow_blank=True,
            max_length=MAX_FILTER_LENGTH,
            trim_whitespace=True,
        ),
        required=False,
        default=list,
        max_length=MAX_FILTER_VALUES,
    )
    job_title = serializers.ListField(
        child=serializers.CharField(
            allow_blank=True,
            max_length=MAX_FILTER_LENGTH,
            trim_whitespace=True,
        ),
        required=False,
        default=list,
        max_length=MAX_FILTER_VALUES,
    )
    industry = serializers.ListField(
        child=serializers.CharField(
            allow_blank=True,
            max_length=MAX_FILTER_LENGTH,
            trim_whitespace=True,
        ),
        required=False,
        default=list,
        max_length=MAX_FILTER_VALUES,
    )
    country = serializers.ListField(
        child=serializers.CharField(
            allow_blank=True,
            max_length=MAX_FILTER_LENGTH,
            trim_whitespace=True,
        ),
        required=False,
        default=list,
        max_length=MAX_FILTER_VALUES,
    )
    company = serializers.ListField(
        child=serializers.CharField(
            allow_blank=True,
            max_length=MAX_FILTER_LENGTH,
            trim_whitespace=True,
        ),
        required=False,
        default=list,
        max_length=MAX_FILTER_VALUES,
    )
    page = serializers.IntegerField(required=False, default=1, min_value=1)
    page_size = serializers.IntegerField(
        required=False,
        default=DEFAULT_PAGE_SIZE,
        min_value=1,
        max_value=MAX_PAGE_SIZE,
    )

    def validate(self, attrs):
        offset = (attrs["page"] - 1) * attrs["page_size"]
        if offset + attrs["page_size"] > MAX_RESULT_WINDOW:
            raise serializers.ValidationError({"page": SEARCH_WINDOW_MESSAGE})
        return attrs

    def to_criteria(self) -> SearchCriteria:
        if not hasattr(self, "validated_data"):
            raise AssertionError("Call is_valid() before converting search parameters.")
        return SearchCriteria(
            q=self.validated_data["q"] or None,
            filters={
                name: [value for value in self.validated_data[name] if value]
                for name in FILTER_FIELDS
            },
            page=self.validated_data["page"],
            page_size=self.validated_data["page_size"],
        )


def search_parameter_data(query_params) -> dict:
    data = {
        name: [value for value in query_params.getlist(name) if value.strip()]
        for name in FILTER_FIELDS
    }
    repeated = {
        name: [REPEATED_SCALAR_MESSAGE]
        for name in SCALAR_QUERY_PARAMETERS
        if len(query_params.getlist(name)) > 1
    }
    if repeated:
        raise serializers.ValidationError(repeated)
    for name in SCALAR_QUERY_PARAMETERS:
        values = query_params.getlist(name)
        if values:
            data[name] = values[0]
    return data


class ProfileSearchResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    full_name = serializers.CharField(allow_blank=True)
    job_title = serializers.CharField(allow_blank=True)
    company = serializers.CharField(allow_blank=True)
    industry = serializers.CharField(allow_blank=True)
    country = serializers.CharField(allow_blank=True)
    skills = serializers.ListField(child=serializers.CharField())
    summary = serializers.CharField(allow_blank=True)


class FacetBucketSerializer(serializers.Serializer):
    value = serializers.CharField()
    count = serializers.IntegerField(min_value=0)


class SearchFacetsSerializer(serializers.Serializer):
    skills = FacetBucketSerializer(many=True)
    job_titles = FacetBucketSerializer(many=True)
    industries = FacetBucketSerializer(many=True)
    countries = FacetBucketSerializer(many=True)
    companies = FacetBucketSerializer(many=True)


class ProfileSearchResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField(min_value=0)
    page = serializers.IntegerField(min_value=1)
    page_size = serializers.IntegerField(min_value=1, max_value=MAX_PAGE_SIZE)
    total_pages = serializers.IntegerField(min_value=0)
    results = ProfileSearchResultSerializer(many=True)
    facets = SearchFacetsSerializer()


class SearchUnavailableResponseSerializer(serializers.Serializer):
    code = serializers.CharField()
    detail = serializers.CharField()


class AuthenticationErrorResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()


class NotFoundResponseSerializer(serializers.Serializer):
    detail = serializers.CharField()


class SearchValidationErrorResponseSerializer(serializers.Serializer):
    q = serializers.ListField(child=serializers.CharField(), required=False)
    skill = serializers.ListField(child=serializers.CharField(), required=False)
    job_title = serializers.ListField(child=serializers.CharField(), required=False)
    industry = serializers.ListField(child=serializers.CharField(), required=False)
    country = serializers.ListField(child=serializers.CharField(), required=False)
    company = serializers.ListField(child=serializers.CharField(), required=False)
    page = serializers.ListField(child=serializers.CharField(), required=False)
    page_size = serializers.ListField(child=serializers.CharField(), required=False)
    non_field_errors = serializers.ListField(child=serializers.CharField(), required=False)
