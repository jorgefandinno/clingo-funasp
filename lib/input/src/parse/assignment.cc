#include <clingo/input/literal.hh>

#include <clingo/input/rewrite/analyze.hh>

#include <clingo/util/immutable_array.hh>

#include "parser_state.hh"

namespace CppClingo::Input::Parse {

namespace {

//! Returns the name of arguments of a term that represents a function, whether is a TermFunction or a TermSymbol with function symbol.
auto assignment_name_and_arguments(ParserState &state, Term term) -> std::optional<std::pair<std::string, PoolArray>> {
    std::string name_str;
    PoolArray pool;
    if (std::holds_alternative<TermFunction>(term)) {
        name_str = std::get<TermFunction>(term).name().view();
        pool = std::get<TermFunction>(term).pool();
    }
    else if (std::holds_alternative<TermSymbol>(term) && std::get<TermSymbol>(term).value().type() == SymbolType::function) {
        name_str = std::get<TermSymbol>(term).value().name().view();
        pool = Util::make_immutable_array<ArgumentTuple>(ArgumentTuple{{}});
    }
    else {
         return std::nullopt;
    }
    return std::make_pair(name_str, pool);
}

auto pool_add(PoolArray pool, Argument arg) -> PoolArray {
    auto new_pool = std::vector<ArgumentTuple>{};
    new_pool.reserve(pool.size());
    for (const auto &tuple : pool) {
        auto arguments = std::vector<Argument>{};
        arguments.reserve(tuple.elems().size() + 1);
        for (const auto &a : tuple.elems()) {
            arguments.emplace_back(a);
        }
        arguments.emplace_back(arg);
        new_pool.emplace_back(ArgumentTuple{arguments});
    }
    return Util::immutable_array<ArgumentTuple>(new_pool);
}

//! Continue parsing a simple assignment.
auto cont_simple_assignment(ParserState &state, Position pos, String name, PoolArray pool) -> std::optional<Lit> {
    if (auto rhs = parse_term(state)) {
        pool = pool_add(pool, *std::move(rhs));
    } else {
        return std::nullopt;
    }
    auto term = TermFunction(Location{pos, state.cursor_pos()}, name, std::move(pool), false);
    return Lit{std::in_place_type<LitSymbolic>, Location{std::move(pos), state.cursor_pos()}, Sign::none, std::move(term)};
}

auto cont_simple_assignment(ParserState &state, Position pos, Term term) -> std::optional<Lit> {
    auto name_and_args = assignment_name_and_arguments(state, term);
    if (!name_and_args) {
        return state.expected<std::nullopt>("<functional term>"); // propagate the error
    }
    auto &[name_str, pool] = *name_and_args;
    auto end_pos = state.cursor_pos();
    auto name = state.store().string_ref("F" + name_str);
    return cont_simple_assignment(state, std::move(pos), name, pool);
}

//! Parse a aggregate element in an assignment.
auto parse_assignment_aggr_elem(ParserState &state) -> std::optional<HdLitAggregateElement> {
    // if the tuple is empty it must be followed by a colon
    if (state.token() == TokenType::sem || state.token() == TokenType::rbrace) {
        return state.expected<std::nullopt>(TokenType::colon, "<term>");
    }
    // parse the tuple
    if (auto tuple =
            state.separated_until(parse_term, TokenType::comma, TokenType::colon, TokenType::sem, TokenType::rbrace)) {
        auto loc = tuple->empty() ? state.loc() : location(tuple->front());
        auto term = TermFunction{loc, state.store().string_ref("NONE"), Util::make_immutable_array<ArgumentTuple>(ArgumentTuple{{}}), false};
        auto lit = Lit{std::in_place_type<LitSymbolic>, loc, Sign::none, std::move(term)};
        // a tuple without condition
        if (state.token() != TokenType::colon) {
            if (!tuple->empty()) {
                loc += location(tuple->back());
            }
            return HdLitAggregateElement{std::move(loc), *std::move(tuple), std::move(lit), {}};
        }
        loc += state.cursor_pos();
        // consume the colon
        state.consume();
        // parse condition
        if (auto cond = state.separated_until(parse_literal, TokenType::comma, TokenType::sem, TokenType::rbrace)) {
            if (!cond->empty()) {
                loc += location(cond->back()).end();
            }
            return HdLitAggregateElement{std::move(loc), *std::move(tuple), std::move(lit), *std::move(cond)};
        }
    }
    return std::nullopt;
}

//! Continue parsing an aggregate in an assignment.
auto cont_assignment_aggregate(ParserState &state, Position pos, Sign sign, LGuard lguard, AggregateFunction fun)
    -> std::optional<HdLit> {
    // parse elements
    if (auto elems = state.delimited(TokenType::lbrace, parse_assignment_aggr_elem, TokenType::sem, TokenType::rbrace)) {
        auto loc = std::move(pos) + state.cursor_pos();
        // consume rbrace
        state.consume();
        // parse optional right guard
        if (auto rguard = parse_rguard(state)) {
            if (*rguard) {
                loc += location((*rguard)->second);
            }
            return HdLitAggregate{std::move(loc), std::move(lguard), fun, *std::move(elems), *std::move(rguard)};
        }
    }
    return std::nullopt;
}

//! Check whether the current token is an aggregate function for assignments and return it.
auto check_assignment_aggregate(TokenType token) ->  std::optional<AggregateFunction> {
    switch (token) {
        case TokenType::sum: {
            return AggregateFunction::sum;
        }
        case TokenType::sump: {
            return AggregateFunction::sump;
        }
        case TokenType::count: {
            return AggregateFunction::count;
        }
        case TokenType::min: {
            return AggregateFunction::min;
        }
        case TokenType::max: {
            return AggregateFunction::max;
        }
        case TokenType::some: {
            return AggregateFunction::some;
        }
        default: {
            return std::nullopt;
        }
    }
}

} // namespace

//! Continue parsing an assignment. It can be simple or contain an aggregate.
auto cont_assignment(ParserState &state, Position pos, Term term) -> std::optional<HdLit> {
    auto name_and_args = assignment_name_and_arguments(state, term);
    if (!name_and_args) {
        return state.expected<std::nullopt>("<functional term>"); // propagate the error
    }
    auto &[name_str, pool] = *name_and_args;
    auto end_pos = state.cursor_pos();
    String name;
    if (auto fun = check_assignment_aggregate(state.token())) {
        state.consume();
        if (*fun == AggregateFunction::some) {
            name = state.store().string_ref("FS" + name_str);
            *fun = AggregateFunction::sum;
        }
        else {
            name = state.store().string_ref("F" + name_str);
        }
        auto term  = TermFunction(Location{pos, end_pos}, name, pool, false);
        return cont_assignment_aggregate(state, pos, Sign::none, LGuard{std::in_place, std::move(term), Relation::equal}, *fun);
    }
    name = state.store().string_ref("F" + name_str);
    auto simple_assignment = cont_simple_assignment(state, std::move(pos), name, pool);
    if (!simple_assignment) {
        return state.expected<std::nullopt>("<term>", "<aggregate>");
    }
    return HdLitSimple{*std::move(simple_assignment)};
}

auto parse_literal_or_simple_assignment(ParserState &state) -> std::optional<Lit> {
    auto pos = state.token_pos();
    auto sign = parse_sign(state);
    if (sign != Sign::none) {
        if (auto term = parse_term(state)) {
            return cont_literal(state, std::move(pos), sign, *std::move(term));
        }
        return std::nullopt;
    }
    // handle atoms or assignment
    if (check_term(state.token())) {
        auto term = parse_term(state);
        if (!term) {
            return std::nullopt;
        }
        if (state.token() == TokenType::assign) {
            state.consume();
            return cont_simple_assignment(state, std::move(pos), *std::move(term));
        }
        return cont_literal(state, std::move(pos), Sign::none, *std::move(term));
    }
    // handle Boolean literals
    if (state.token() == TokenType::true_ || state.token() == TokenType::false_) {
        return cont_literal(state, std::move(pos), Sign::none);
    }
    return std::nullopt;
}

///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////

} // namespace CppClingo::Input::Parse