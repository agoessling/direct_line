#pragma once

#include <type_traits>

template <typename F>
concept NoThrowCallable = std::is_nothrow_invocable_v<F>;
