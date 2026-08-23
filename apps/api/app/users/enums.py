"""Shared string-backed enums for the users domain."""

import enum


class UserType(enum.StrEnum):
    customer = "customer"
    courier = "courier"
    restaurant = "restaurant"
    restaurant_staff = "restaurant_staff"


class AuthProvider(enum.StrEnum):
    email = "email"
    phone = "phone"
    google = "google"
    github = "github"
    linkedin = "linkedin"


class VehicleType(enum.StrEnum):
    bike = "bike"
    motorcycle = "motorcycle"
    car = "car"


class StaffRole(enum.StrEnum):
    manager = "manager"
    waiter = "waiter"
    cashier = "cashier"


class DevicePlatform(enum.StrEnum):
    android = "android"
    ios = "ios"
    web = "web"
