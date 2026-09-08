import { useState } from "react";

import type { FacetEntry } from "../api/profiles";
import { normalizeValueKey, normalizeValues } from "./searchState";

interface FacetFilterProps {
  legend: string;
  name: string;
  options: FacetEntry[];
  selected: string[];
  onChange: (values: string[]) => void;
}

const INITIAL_OPTION_COUNT = 6;

export function FacetFilter({ legend, name, options, selected, onChange }: FacetFilterProps) {
  const [expanded, setExpanded] = useState(false);
  const countByValue = new Map(options.map((option) => [normalizeValueKey(option.value), option.count]));
  const selectedKeys = new Set(selected.map(normalizeValueKey));
  const values = normalizeValues([...selected, ...options.map((option) => option.value)]);
  const visibleValues = expanded ? values : values.slice(0, INITIAL_OPTION_COUNT);

  const toggle = (value: string) => {
    const valueKey = normalizeValueKey(value);
    onChange(
      selectedKeys.has(valueKey)
        ? selected.filter((selectedValue) => normalizeValueKey(selectedValue) !== valueKey)
        : normalizeValues([...selected, value]),
    );
  };

  return (
    <fieldset className="facet-group">
      <legend>{legend}</legend>
      {visibleValues.length > 0 ? (
        <div className="facet-options">
          {visibleValues.map((value, index) => {
            const count = countByValue.get(normalizeValueKey(value));
            const inputId = `filter-${name}-${index}`;
            return (
              <label className="facet-option" htmlFor={inputId} key={value}>
                <input
                  id={inputId}
                  name={name}
                  type="checkbox"
                  checked={selectedKeys.has(normalizeValueKey(value))}
                  onChange={() => toggle(value)}
                />
                <span className="facet-value">{value}</span>
                {count === undefined ? (
                  <span className="facet-count">selected</span>
                ) : (
                  <span className="facet-count" aria-label={`${count} matching profiles`}>
                    {count}
                  </span>
                )}
              </label>
            );
          })}
        </div>
      ) : (
        <p className="facet-empty">No options available</p>
      )}
      {values.length > INITIAL_OPTION_COUNT ? (
        <button className="text-button facet-more" type="button" onClick={() => setExpanded(!expanded)}>
          {expanded ? "Show fewer" : `Show ${values.length - INITIAL_OPTION_COUNT} more`}
        </button>
      ) : null}
    </fieldset>
  );
}
