from __future__ import annotations

from ro_crate_run import adapters


def test_engine_homepage_for_each_real_engine() -> None:
    # Every adapter in the registry resolves to a non-null homepage so the engine
    # SoftwareApplication always gets a `url`.
    for adapter in adapters.ADAPTERS:
        assert adapters.engine_homepage(adapter.engine_name) == adapter.homepage
        assert adapters.engine_homepage(adapter.engine_name)


def test_engine_homepage_covers_the_four_known_engines() -> None:
    assert adapters.engine_homepage("cwl") == "https://www.commonwl.org/"
    assert adapters.engine_homepage("nextflow") == "https://www.nextflow.io/"
    assert adapters.engine_homepage("snakemake") == "https://snakemake.github.io/"
    assert adapters.engine_homepage("galaxy") == "https://galaxyproject.org/"


def test_imported_ro_crate_homepage_is_explicitly_none() -> None:
    # An imported crate names no executing engine, so it has no canonical homepage.
    assert "imported-ro-crate" in adapters.ENGINE_HOMEPAGES
    assert adapters.engine_homepage("imported-ro-crate") is None


def test_engine_homepage_unknown_is_none() -> None:
    assert adapters.engine_homepage("cwltool") is None
    assert adapters.engine_homepage("wdl") is None
    assert adapters.engine_homepage("does-not-exist") is None


def test_registry_has_no_stale_keys() -> None:
    # The homepage map is derived from the adapter registry plus the explicit extras;
    # it must not carry engine names no adapter produces (e.g. the old cwltool/wdl keys).
    real = {adapter.engine_name for adapter in adapters.ADAPTERS}
    extra = {"imported-ro-crate"}
    assert set(adapters.ENGINE_HOMEPAGES) == real | extra
